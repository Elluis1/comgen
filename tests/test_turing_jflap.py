"""El .jff de una máquina de Turing. No abre Ollama.

El blanco del archivo es una etiqueta vacía. Al volver a leerlo, esa
etiqueta es el blanco de la máquina. Una flecha que falta no se completa
y no aparece un pozo.
"""

import asyncio
import json
import time
import unicodedata
import xml.etree.ElementTree as ET
from unittest.mock import patch
from xml.parsers.expat import ParserCreate

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sanitize import xml_char_allowed
from app.store import MAX_SESSIONS, store
from app.turing import TuringMachine, TuringState, TuringTransition, run, start, validate_tm
from app.turing_jflap import (
    MAX_XML_BYTES,
    TuringJflapError,
    export_turing_jflap,
    import_turing_jflap,
)

MINIMAL = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<structure>
	<type>turing</type>
	<automaton>
		<state id="0" name="q0">
			<initial/>
		</state>
		<state id="1" name="qf">
			<final/>
		</state>
		<transition>
			<from>0</from>
			<to>1</to>
			<read>a</read>
			<write>b</write>
			<move>R</move>
		</transition>
	</automaton>
</structure>
"""

FA_FILE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<structure>
	<type>fa</type>
	<automaton>
		<state id="0" name="q0"><initial/></state>
	</automaton>
</structure>
"""

# Así lo guarda JFLAP 7.1: el comentario va pegado a la raíz, y el blanco
# es <read/> / <write/>. «Ret 1» es un nombre de verdad, con un espacio.
JFLAP_71 = """<?xml version="1.0" encoding="UTF-8" standalone="no"?><!--Created with JFLAP 7.1.--><structure>
	<type>turing</type>
	<automaton>
		<!--The list of states.-->
		<state id="0" name="Ret 1">
			<x>68.0</x>
			<y>132.0</y>
			<initial/>
		</state>
		<state id="1" name="qf">
			<x>214.0</x>
			<y>132.0</y>
			<final/>
		</state>
		<!--The list of transitions.-->
		<transition>
			<from>0</from>
			<to>1</to>
			<read>a</read>
			<write>b</write>
			<move>R</move>
		</transition>
		<transition>
			<from>0</from>
			<to>1</to>
			<read/>
			<write/>
			<move>S</move>
		</transition>
	</automaton>
</structure>
"""

BYPASS_DTD = """<?x <structure ?>
<!DOCTYPE s [<!ENTITY x "turing">]>
<structure><type>&x;</type><automaton><state id="0" name="q0"><initial/><final/></state></automaton></structure>
"""


def _item27() -> TuringMachine:
    from test_turing import _an_bn

    return _an_bn()


def _edge(state: str, read: str, to: str, write: str, move: str) -> TuringTransition:
    return TuringTransition(state, read, to, write, move)


def _strict_xml(document: str) -> ET.Element:
    for char in document:
        assert xml_char_allowed(char), hex(ord(char))
    parser = ParserCreate(encoding="UTF-8")
    parser.Parse(document.encode("utf-8"), True)
    return ET.fromstring(document.encode("utf-8"))


def _arrows(machine: TuringMachine) -> list[tuple[str, str, str, str, str]]:
    return [
        (item.state, item.read, item.to, item.write, item.move)
        for item in machine.transitions
    ]


def _profile(machine: TuringMachine) -> list[tuple[str, bool, bool]]:
    return [(state.id, state.initial, state.final) for state in machine.states]


def test_item27_machine_roundtrips_without_a_sink_or_ollama():
    machine = _item27()
    xml = export_turing_jflap(machine)
    root = _strict_xml(xml)
    assert root.findtext("type") == "turing"
    assert "<type>turing</type>" in xml
    names = [state.get("name") for state in root.findall("./automaton/state")]
    assert names == ["q0", "q1", "q2", "q3", "q4", "qf"]
    assert "pozo" not in names
    assert "pozo" not in xml
    transitions = root.findall("./automaton/transition")
    assert len(transitions) == len(machine.transitions)
    moves = {item.findtext("move") for item in transitions}
    assert moves == {"L", "R", "S"}
    ids = {state.get("name"): state.get("id") for state in root.findall("./automaton/state")}
    stay = [
        item
        for item in transitions
        if item.findtext("from") == ids["q4"] and item.findtext("to") == ids["qf"]
    ]
    assert len(stay) == 1
    assert stay[0].findtext("move") == "S"
    assert stay[0].find("read").text is None
    assert stay[0].find("write").text is None
    assert "<read />" in xml
    assert "<write />" in xml
    assert "El blanco de Comgen es _ ." in xml
    for item in transitions:
        assert (item.find("read").text or "") != "_"
        assert (item.find("write").text or "") != "_"

    imported = import_turing_jflap(xml)
    assert _profile(imported) == _profile(machine)
    assert imported.blank == "_"
    assert set(imported.tape_alphabet) == {"a", "b", "X", "Y", "_"}
    assert _arrows(imported) == _arrows(machine)
    assert imported.description == machine.description
    assert "_prepared" not in xml
    for word in ("ab", "aabb", "aaabbb"):
        before = run(machine, word)
        after = run(imported, word)
        assert after.status == "accept", word
        assert after.accepted is True
        assert after.steps_run == before.steps_run
        assert after.tape == before.tape
        assert after.head == before.head
    for word in ("", "aab", "ba", "abb"):
        after = run(imported, word)
        assert after.status == "reject", word
        assert after.accepted is False
        assert "falta la transición" in after.message
        assert "pozo" not in after.message


def test_a_missing_transition_is_not_filled_and_the_language_stays():
    transitions = [_edge("q0", "a", "q1", "b", "R")]
    machine = TuringMachine(
        states=[TuringState("q0", initial=True, final=True), TuringState("q1")],
        tape_alphabet=["a", "b", "_"],
        blank="_",
        description="parcial",
        transitions=transitions,
    )
    xml = export_turing_jflap(machine)
    root = _strict_xml(xml)
    assert len(root.findall("./automaton/transition")) == 1
    assert len(root.findall("./automaton/state")) == 2
    assert "pozo" not in xml
    assert machine.transitions is transitions
    assert len(machine.states) == 2
    imported = import_turing_jflap(xml)
    assert _profile(imported) == _profile(machine)
    assert _arrows(imported) == _arrows(machine)
    assert imported.blank == "_"
    for word in ("", "a", "b", "aa", "ab", "ba"):
        before = run(machine, word)
        after = run(imported, word)
        assert after.status == before.status, word
        assert after.accepted == before.accepted
        assert after.message == before.message


def test_minimal_jflap_xml_uses_underscore_when_the_comment_is_absent():
    imported = import_turing_jflap(MINIMAL)
    assert _profile(imported) == [("q0", True, False), ("qf", False, True)]
    assert imported.blank == "_"
    assert _arrows(imported) == [("q0", "a", "qf", "b", "R")]
    assert run(imported, "a").status == "accept"
    assert run(imported, "").status == "reject"
    assert run(imported, "b").status == "reject"
    again = import_turing_jflap(export_turing_jflap(imported))
    assert _arrows(again) == _arrows(imported)
    assert again.blank == "_"


def test_empty_tags_are_not_an_explicit_underscore():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <structure><type>turing</type><automaton>
        <state id="0" name="q0"><initial/></state>
        <state id="1" name="qf"><final/></state>
        <transition><from>0</from><to>0</to><read>_</read><write>_</write><move>R</move></transition>
        <transition><from>0</from><to>1</to><read></read><write></write><move>S</move></transition>
    </automaton></structure>
    """
    imported = import_turing_jflap(xml)
    assert imported.blank != "_"
    reads = {item.read for item in imported.transitions}
    assert "_" in reads
    assert imported.blank in reads
    assert len(reads) == 2


def test_a_blank_other_than_underscore_roundtrips_as_empty_tags():
    machine = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "□"],
        blank="□",
        description="blanco cuadrado",
        transitions=[
            _edge("q0", "a", "qf", "a", "R"),
            _edge("q0", "□", "qf", "a", "S"),
        ],
    )
    xml = export_turing_jflap(machine)
    root = _strict_xml(xml)
    assert "El blanco de Comgen es □ ." in xml
    stay = [item for item in root.findall("./automaton/transition") if item.findtext("move") == "S"]
    assert len(stay) == 1
    assert stay[0].find("read").text is None
    assert stay[0].findtext("write") == "a"
    imported = import_turing_jflap(xml)
    assert imported.blank == "□"
    assert _arrows(imported) == _arrows(machine)
    assert run(imported, "a").status == "accept"
    assert run(imported, "").accepted is True


def test_epsilon_lookalikes_jamo_and_operators_stay_distinct():
    lead = "ᄀ"
    machine = TuringMachine(
        states=[TuringState("q0", initial=True, final=True)],
        tape_alphabet=["ε", "ɛ", lead, "&", "-"],
        blank="-",
        transitions=[
            _edge("q0", "ε", "q0", "ε", "R"),
            _edge("q0", "ɛ", "q0", "ɛ", "S"),
            _edge("q0", lead, "q0", lead, "L"),
            _edge("q0", "&", "q0", "&", "S"),
        ],
    )
    xml = export_turing_jflap(machine)
    _strict_xml(xml)
    assert "<read>&amp;</read>" in xml
    assert "가" not in xml
    imported = import_turing_jflap(xml)
    assert imported.blank == "-"
    assert {item.read for item in imported.transitions} == {"ε", "ɛ", lead, "&"}
    assert run(imported, "ε").status == "accept"
    assert run(imported, lead).status == "accept"


def test_names_quotes_and_a_comment_with_a_double_dash_stay_xml():
    quoted = 'a"b'
    machine = TuringMachine(
        states=[TuringState(quoted, initial=True, final=True)],
        tape_alphabet=["&", "_"],
        blank="_",
        description="a--b\u0001",
        transitions=[_edge(quoted, "&", quoted, "&", "S")],
    )
    xml = export_turing_jflap(machine)
    _strict_xml(xml)
    assert "\u0001" not in xml
    assert "--" not in xml.split("<automaton>", 1)[1].split("</automaton>", 1)[0] or "—" in xml
    assert "-->" not in xml.split("<!--", 1)[1].split("El blanco", 1)[0]
    imported = import_turing_jflap(xml)
    assert imported.states[0].id == quoted
    assert imported.transitions[0].read == "&"
    assert imported.description == "a—b"
    assert machine.description == "a--b\u0001"


def test_export_does_not_serialize_the_step_cache():
    machine = _item27()
    start(machine, "ab")
    assert getattr(machine, "_prepared_cache", None) is not None
    xml = export_turing_jflap(machine)
    assert "_prepared" not in xml
    assert "_checked" not in xml
    imported = import_turing_jflap(xml)
    assert not hasattr(imported, "_prepared_cache")
    assert run(imported, "ab").accepted is True


def test_bad_files_fail_in_spanish():
    with pytest.raises(TuringJflapError, match="XML"):
        import_turing_jflap("hola")
    with pytest.raises(TuringJflapError, match="XML"):
        import_turing_jflap("<structure>")
    with pytest.raises(TuringJflapError, match="máquina"):
        import_turing_jflap(FA_FILE)
    grammar = FA_FILE.replace("<type>fa</type>", "<type>grammar</type>")
    with pytest.raises(TuringJflapError, match="máquina"):
        import_turing_jflap(grammar)
    doctype = """<?xml version="1.0"?>
    <!DOCTYPE structure [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <structure><type>&xxe;</type></structure>
    """
    with pytest.raises(TuringJflapError, match="DTD"):
        import_turing_jflap(doctype)
    lowercase = MINIMAL.replace("<move>R</move>", "<move>l</move>")
    with pytest.raises(TuringJflapError, match="L, R ni S"):
        import_turing_jflap(lowercase)
    duplicated = MINIMAL.replace(
        "</automaton>",
        "<transition><from>0</from><to>1</to><read>a</read><write>a</write><move>L</move></transition></automaton>",
    )
    with pytest.raises(TuringJflapError, match="dos transiciones"):
        import_turing_jflap(duplicated)
    tapes = MINIMAL.replace("</automaton>", "<tapes>2</tapes></automaton>")
    with pytest.raises(TuringJflapError, match="una sola cinta"):
        import_turing_jflap(tapes)
    with pytest.raises(TuringJflapError, match="grande"):
        import_turing_jflap("a" * (MAX_XML_BYTES + 1))


def test_nfd_names_come_back_composed():
    nfd = unicodedata.normalize("NFD", "é")
    assert nfd != "é"
    machine = TuringMachine(
        states=[TuringState(nfd, initial=True, final=True)],
        tape_alphabet=[nfd, "_"],
        blank="_",
        transitions=[_edge(nfd, nfd, nfd, nfd, "S")],
    )
    xml = export_turing_jflap(machine)
    assert nfd not in xml
    imported = import_turing_jflap(xml)
    assert imported.states[0].id == "é"
    assert "é" in imported.tape_alphabet
    assert imported.blank == "_"


def test_the_session_simulates_the_imported_machine_and_keeps_the_automaton():
    async def fake_chat(*_args, **_kwargs):
        raise AssertionError("El .jff de Turing no tiene que llamar a Ollama.")

    machine = _item27()
    xml = export_turing_jflap(machine)
    with TestClient(app) as client, patch("app.service.chat", fake_chat):
        missing = client.post("/api/sessions/no-existe/turing", content=b"hola")
        assert missing.status_code == 404
        assert "Recargá" in missing.json()["detail"]

        session_id = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{session_id}/examples/paridad")
        assert loaded.status_code == 200
        before = loaded.json()["automaton"]

        garbage = client.post(f"/api/sessions/{session_id}/turing", content=b"esto no es xml")
        assert garbage.status_code == 400
        assert "XML" in garbage.json()["detail"]
        foreign = client.post(f"/api/sessions/{session_id}/turing", content=FA_FILE.encode("utf-8"))
        assert foreign.status_code == 400
        detail = foreign.json()["detail"]
        assert "máquina" in detail
        assert "fa" in detail

        empty = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "ab"})
        assert empty.status_code == 409
        assert "máquina" in empty.json()["detail"]

        started = time.perf_counter()
        huge = client.post(
            f"/api/sessions/{session_id}/turing",
            content=b"a" * (MAX_XML_BYTES + 1),
        )
        assert time.perf_counter() - started < 1
        assert huge.status_code == 400
        assert "grande" in huge.json()["detail"]

        minimal = client.post(f"/api/sessions/{session_id}/turing", content=MINIMAL.encode("utf-8"))
        assert minimal.status_code == 200
        body = minimal.json()
        assert body["machine"]["blank"] == "_"
        assert "_prepared" not in json.dumps(body)
        assert "simular" in body["message"]
        accepted = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "a"})
        assert accepted.status_code == 200
        assert accepted.json()["accepted"] is True
        assert accepted.json()["steps"] == []
        rejected = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": ""})
        assert rejected.json()["accepted"] is False
        blank = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "_"})
        assert blank.status_code == 409
        assert "blanco" in blank.json()["detail"]

        parity = client.post(f"/api/sessions/{session_id}/simulate", json={"word": "11"})
        assert parity.status_code == 200
        assert parity.json()["accepted"] is True
        still = client.get(f"/api/sessions/{session_id}/export")
        assert still.status_code == 200
        assert "<type>fa</type>" in still.text
        assert still.text
        assert loaded.json()["automaton"]["states"] == before["states"]

        loaded_tm = client.post(f"/api/sessions/{session_id}/turing", content=xml.encode("utf-8"))
        assert loaded_tm.status_code == 200
        ran = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "ab"})
        assert ran.status_code == 200
        result = ran.json()
        assert result["accepted"] is True
        assert result["state"] == "qf"
        assert result["tape"] == ["X", "Y", "_"]
        assert result["head"] == 2
        assert result["steps"] == []
        denied = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "aab"})
        assert denied.json()["accepted"] is False
        assert "falta la transición" in denied.json()["message"]

        exported = client.get(f"/api/sessions/{session_id}/turing/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("application/xml")
        disposition = exported.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="maquina-')
        assert disposition.endswith('.jff"')
        assert "\n" not in disposition
        assert "\r" not in disposition
        assert disposition.count('"') == 2
        assert "<type>turing</type>" in exported.text
        brought = import_turing_jflap(exported.text)
        assert _arrows(brought) == _arrows(machine)

        reset = client.post(f"/api/sessions/{session_id}/reset")
        assert reset.status_code == 200
        gone = client.post(f"/api/sessions/{session_id}/turing/run", json={"word": "ab"})
        assert gone.status_code == 409


def test_a_jflap_71_file_with_the_header_and_empty_tags_imports():
    imported = import_turing_jflap(JFLAP_71)
    assert _profile(imported) == [("Ret 1", True, False), ("qf", False, True)]
    assert imported.blank == "_"
    assert imported.description == ""
    assert _arrows(imported) == [
        ("Ret 1", "a", "qf", "b", "R"),
        ("Ret 1", "_", "qf", "_", "S"),
    ]
    assert run(imported, "a").status == "accept"
    assert run(imported, "").accepted is True
    assert "Created with JFLAP" not in imported.description


def test_imported_names_keep_an_internal_space_and_reject_padding():
    imported = import_turing_jflap(MINIMAL.replace('name="q0"', 'name="Ret 1"', 1))
    assert imported.states[0].id == "Ret 1"
    assert run(imported, "a").accepted is True
    again = import_turing_jflap(export_turing_jflap(imported))
    assert again.states[0].id == "Ret 1"
    assert _arrows(again) == _arrows(imported)

    rejected = (
        'name=""',
        'name="   "',
        'name=" q0"',
        'name="q0 "',
        'name=" Ret 1 "',
        'name="\tq0"',
        'name="q0\n"',
        'name="\u00a0q0"',
    )
    for attribute in rejected:
        xml = MINIMAL.replace('name="q0"', attribute, 1)
        with pytest.raises(TuringJflapError, match="está vacío o tiene espacios"):
            import_turing_jflap(xml)

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        for attribute in rejected:
            xml = MINIMAL.replace('name="q0"', attribute, 1)
            response = client.post(
                f"/api/sessions/{session_id}/turing",
                content=xml.encode("utf-8"),
            )
            assert response.status_code == 400, attribute
            assert response.json()["detail"] == "El estado no sirve: está vacío o tiene espacios."

    spaced = TuringMachine(
        states=[TuringState("Ret 1", initial=True, final=True)],
        tape_alphabet=["a", "_"],
        blank="_",
        transitions=[_edge("Ret 1", "a", "Ret 1", "a", "S")],
    )
    assert validate_tm(spaced) == []
    empty_state = TuringMachine(
        states=[TuringState("", initial=True)],
        tape_alphabet=["_"],
        blank="_",
        transitions=[],
    )
    assert any("vacío" in item for item in validate_tm(empty_state))
    tabbed = TuringMachine(
        states=[TuringState("Ret\t1", initial=True)],
        tape_alphabet=["_"],
        blank="_",
        transitions=[],
    )
    assert any("espacios" in item for item in validate_tm(tabbed))

    nbsp = MINIMAL.replace("name=\"q0\"", "name=\"Ret\u00a01\"", 1)
    with pytest.raises(TuringJflapError, match="espacios"):
        import_turing_jflap(nbsp)
    too_long = MINIMAL.replace('name="q0"', 'name="' + ("ab" * 40) + '"', 1)
    with pytest.raises(TuringJflapError, match="largo"):
        import_turing_jflap(too_long)


def test_a_description_that_copies_the_blank_marker_roundtrips():
    text = "El blanco de Comgen es Q ."
    machine = TuringMachine(
        states=[TuringState("q0", initial=True), TuringState("qf", final=True)],
        tape_alphabet=["a", "b", "_"],
        blank="_",
        description=text,
        transitions=[_edge("q0", "a", "qf", "b", "R")],
    )
    xml = export_turing_jflap(machine)
    assert xml.index("El blanco de Comgen es _ .") < xml.index(text)
    imported = import_turing_jflap(xml)
    assert imported.description == text
    assert imported.blank == "_"
    assert _arrows(imported) == _arrows(machine)
    assert run(imported, "a").accepted is True
    again = import_turing_jflap(export_turing_jflap(imported))
    assert again.description == text
    assert again.blank == "_"


def test_a_doctype_behind_a_processing_instruction_and_a_laugh_return_400():
    mentioned = MINIMAL.replace(
        "<automaton>",
        "<automaton><!-- el texto <!DOCTYPE y ENTITY no es un DTD -->",
        1,
    )
    assert import_turing_jflap(mentioned).states[0].id == "q0"
    with pytest.raises(TuringJflapError, match="DTD"):
        import_turing_jflap(BYPASS_DTD)
    started = time.perf_counter()
    with pytest.raises(TuringJflapError, match="DTD"):
        import_turing_jflap(_billion_laughs())
    assert time.perf_counter() - started < 1

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        started = time.perf_counter()
        bypass = client.post(
            f"/api/sessions/{session_id}/turing",
            content=BYPASS_DTD.encode("utf-8"),
        )
        laugh = client.post(
            f"/api/sessions/{session_id}/turing",
            content=_billion_laughs().encode("utf-8"),
        )
        elapsed = time.perf_counter() - started
    assert elapsed < 1
    for response in (bypass, laugh):
        assert response.status_code == 400
        assert "DTD" in response.json()["detail"]


def test_a_chunked_body_without_content_length_stops_past_one_mebibyte():
    block = b"a" * (64 * 1024)
    cap = MAX_XML_BYTES * 4
    produced = 0

    async def oversized():
        nonlocal produced
        while produced < cap:
            produced += len(block)
            yield block

    async def small():
        data = MINIMAL.encode("utf-8")
        for index in range(0, len(data), 64):
            yield data[index : index + 64]

    async def post():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            session_id = (await client.post("/api/sessions")).json()["id"]
            url = f"/api/sessions/{session_id}/turing"
            huge = client.build_request("POST", url, content=oversized())
            assert "content-length" not in {key.lower() for key in huge.headers}
            started = time.perf_counter()
            rejected = await client.send(huge)
            elapsed = time.perf_counter() - started
            loaded = await client.post(url, content=small())
            return rejected, elapsed, loaded

    rejected, elapsed, loaded = asyncio.run(post())
    assert rejected.status_code == 400
    assert "grande" in rejected.json()["detail"]
    assert elapsed < 1
    assert MAX_XML_BYTES < produced <= MAX_XML_BYTES + len(block)
    assert produced < cap
    assert loaded.status_code == 200
    assert loaded.json()["machine"]["blank"] == "_"


def test_a_content_length_that_is_not_ascii_decimal_is_400():
    # ¹ ² ³ son latin-1. isdigit() da True e int() tira. El encabezado llega así.
    samples = {
        "¹": b"\xb9",
        "²": b"\xb2",
        "³": b"\xb3",
        "abc": b"abc",
        "1.5": b"1.5",
        "": b"",
    }

    async def post(header: bytes) -> tuple[int, str]:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/sessions/no-existe/turing",
            "raw_path": b"/api/sessions/no-existe/turing",
            "query_string": b"",
            "headers": [(b"content-length", header)],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": b"hola", "more_body": False}

        messages: list[dict] = []

        async def send(message):
            messages.append(message)

        await app(scope, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        body = b"".join(
            item.get("body", b"") for item in messages if item["type"] == "http.response.body"
        )
        return start["status"], body.decode("utf-8")

    async def run():
        results = []
        for label, header in samples.items():
            results.append((label, *await post(header)))
        return results

    for label, status, body in asyncio.run(run()):
        assert status == 400, label
        assert "no es un número" in body
        assert "Internal Server Error" not in body


def _billion_laughs() -> str:
    """Diez niveles. Expandido son gigabytes. El texto del archivo es chico."""
    lines = ['<?xml version="1.0"?>', "<!DOCTYPE lolz [", '<!ENTITY lol "lol">']
    previous = "lol"
    for index in range(1, 10):
        lines.append(f'<!ENTITY lol{index} "' + f"&{previous};" * 10 + '">')
        previous = f"lol{index}"
    lines.append("]>")
    lines.append(f"<structure><type>&{previous};</type></structure>")
    return "\n".join(lines)


def test_a_session_with_a_machine_is_not_dropped_before_an_empty_one(monkeypatch):
    assert MAX_SESSIONS == 128
    monkeypatch.setattr("app.store.MAX_SESSIONS", 2)
    with store._registry:
        store._sessions.clear()
        store._locks.clear()
        store._guards.clear()
    with TestClient(app) as client:
        kept = client.post("/api/sessions").json()["id"]
        loaded = client.post(f"/api/sessions/{kept}/turing", content=MINIMAL.encode("utf-8"))
        assert loaded.status_code == 200
        empty = client.post("/api/sessions").json()["id"]
        newest = client.post("/api/sessions").json()["id"]
        assert client.post(f"/api/sessions/{kept}/turing/run", json={"word": "a"}).status_code == 200
        assert client.get(f"/api/sessions/{empty}/export").status_code == 404
        assert client.post(f"/api/sessions/{newest}/examples/paridad").status_code == 200
