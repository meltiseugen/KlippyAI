from __future__ import annotations

from typing import Any

from pydantic import BaseModel as PydanticBaseModel


class BaseModel(PydanticBaseModel):
    @classmethod
    def model_validate(cls, value: Any) -> Any:
        return cls.parse_obj(value)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.dict(*args, **kwargs)
