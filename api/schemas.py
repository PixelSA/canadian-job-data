from pydantic import BaseModel


class SearchOut(BaseModel):
    key: str      # "data analyst|alberta"
    role: str
    region: str

    @classmethod
    def from_key(cls, key: str) -> "SearchOut":
        role, region = key.split("|", 1)
        return cls(key=key, role=role, region=region)