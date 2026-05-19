"""Demo file with several Pydantic v1 patterns to migrate."""

from pydantic import BaseModel, validator


class User(BaseModel):
    name: str
    age: int

    class Config:
        anystr_strip_whitespace = True

    @validator("name")
    def check_name(cls, v):
        return v


def make() -> None:
    u = User.parse_obj({"name": "Ada", "age": 36})
    print(u.dict())
    print(u.json())
    u2 = u.copy()
    print(u2)
