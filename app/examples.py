from dataclasses import dataclass

from app.schemas import FiniteAutomaton, State, Transition


@dataclass(frozen=True)
class Example:
    id: str
    title: str
    blurb: str
    automaton: FiniteAutomaton
    probes: tuple[str, ...] = ()


def _even_ones() -> FiniteAutomaton:
    return FiniteAutomaton(
        deterministic=True,
        alphabet=["0", "1"],
        description="Cadenas binarias con cantidad par de unos",
        states=[
            State(id="q0", initial=True, final=True),
            State(id="q1", initial=False, final=False),
        ],
        transitions=[
            Transition(from_state="q0", to="q0", read="0"),
            Transition(from_state="q0", to="q1", read="1"),
            Transition(from_state="q1", to="q1", read="0"),
            Transition(from_state="q1", to="q0", read="1"),
        ],
    )


def _ends_with_01() -> FiniteAutomaton:
    return FiniteAutomaton(
        deterministic=True,
        alphabet=["0", "1"],
        description="Cadenas binarias que terminan en 01",
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=False),
            State(id="q2", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="0"),
            Transition(from_state="q0", to="q0", read="1"),
            Transition(from_state="q1", to="q1", read="0"),
            Transition(from_state="q1", to="q2", read="1"),
            Transition(from_state="q2", to="q1", read="0"),
            Transition(from_state="q2", to="q0", read="1"),
        ],
    )


def _a_star_epsilon() -> FiniteAutomaton:
    # q0 llega a q2 por épsilon. q2 es final y vuelve a sí mismo con a: el
    # lenguaje es a*. b está en el alfabeto y no tiene flecha, así que rechaza.
    return FiniteAutomaton(
        deterministic=False,
        alphabet=["a", "b"],
        description="Cadenas de a*",
        states=[
            State(id="q0", initial=True, final=False),
            State(id="q1", initial=False, final=False),
            State(id="q2", initial=False, final=True),
        ],
        transitions=[
            Transition(from_state="q0", to="q1", read="ε"),
            Transition(from_state="q1", to="q2", read="λ"),
            Transition(from_state="q2", to="q2", read="a"),
        ],
    )


EXAMPLES: dict[str, Example] = {
    "paridad": Example(
        id="paridad",
        title="Paridad de unos",
        blurb=(
            "q0 lleva la cantidad par de unos y es el estado final. "
            "q1 lleva la cantidad impar. Leer 0 deja el estado igual; leer 1 lo cambia."
        ),
        automaton=_even_ones(),
        probes=("", "0", "1", "11"),
    ),
    "termina-en-01": Example(
        id="termina-en-01",
        title="Termina en 01",
        blurb=(
            "q0 no vio el comienzo del sufijo. q1 termina en 0. "
            "q2 termina en 01 y es el único estado final."
        ),
        automaton=_ends_with_01(),
        probes=("", "01", "1", "001"),
    ),
    "a-estrella": Example(
        id="a-estrella",
        title="a* con épsilon",
        blurb=(
            "q0 llega a q2 por dos épsilon. q2 es final y tiene un lazo en a, "
            "así que el lenguaje es a*. b está en el alfabeto y no tiene flecha. "
            "Determinizar arma el AFD por subconjuntos."
        ),
        automaton=_a_star_epsilon(),
        probes=("", "a", "aa", "b"),
    ),
}
