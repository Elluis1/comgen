from pydantic import BaseModel, ConfigDict, Field, field_validator


class State(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    initial: bool = False
    final: bool = False


class Transition(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_state: str = Field(alias="from")
    to: str
    read: str = ""


class FiniteAutomaton(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    kind: str = "fa"
    deterministic: bool = True
    alphabet: list[str] = Field(default_factory=list)
    states: list[State] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    description: str = ""

    def dump(self) -> dict:
        payload = self.model_dump(by_alias=True)
        payload["kind"] = "fa"
        return payload


class SequenceBlock(BaseModel):
    """Un tramo de una secuencia: un símbolo y cuántas veces se repite.

    repeat es "*", "+" o un número en texto ("3"). El modelo chico solo manda
    estos parámetros; el autómata lo arma el código.
    """

    model_config = ConfigDict(extra="ignore")

    symbol: str = ""
    repeat: str | int = "1"

    @field_validator("repeat", mode="before")
    @classmethod
    def _repeat_is_not_bool(cls, value: object) -> object:
        # Pydantic toma true como el entero 1. «true» no es «una vez».
        if isinstance(value, bool):
            raise ValueError("la repetición tiene que ser *, + o un número")
        return value


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    kind: str = "fa"
    pattern: str = ""
    description: str = ""
    explanation: str = ""
    deterministic: bool = True
    alphabet: list[str] = Field(default_factory=list)
    states: list[State] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    family: str = ""
    base: int | None = None
    modulus: int | None = None
    remainder: int | None = None
    word: str = ""
    symbol: str = ""
    blocks: list[SequenceBlock] = Field(default_factory=list)
    accept: list[str] = Field(default_factory=list)
    reject: list[str] = Field(default_factory=list)
