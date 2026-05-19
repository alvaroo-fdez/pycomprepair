"""Demo file with several Pydantic v1 patterns to migrate."""

from pydantic import BaseModel, validator
from pydantic import field_validator
from pydantic import ConfigDict


class User(BaseModel):
    name: str
    age: int
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("name")
    def check_name(cls, v):
        return v


def make() -> None:
    u = User.model_validate({"name": "Ada", "age": 36})
    print(u.model_dump())
    print(u.model_dump_json())
    u2 = u.model_copy()
    print(u2)
