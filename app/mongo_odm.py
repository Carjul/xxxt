from copy import deepcopy
from datetime import datetime
from typing import Any


class Criterion:
    def __init__(self, field: str, op: str, value: Any):
        self.field = field
        self.op = op
        self.value = value


class Sort:
    def __init__(self, field: str, direction: int):
        self.field = field
        self.direction = direction


class Field:
    def __init__(self, default: Any = None):
        self.default = default
        self.name = ""

    def __set_name__(self, owner, name):
        self.name = name
        owner.__fields__ = getattr(owner, "__fields__", []) + [name]

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.get(self.name, self.default_value())

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value

    def __eq__(self, other):
        return Criterion(self.name, "eq", other)

    def __ne__(self, other):
        return Criterion(self.name, "ne", other)

    def in_(self, values):
        return Criterion(self.name, "in", list(values))

    def isnot(self, value):
        return Criterion(self.name, "ne", value)

    def is_(self, value):
        return Criterion(self.name, "eq", value)

    def desc(self):
        return Sort(self.name, -1)

    def asc(self):
        return Sort(self.name, 1)

    def default_value(self):
        if callable(self.default):
            return self.default()
        return deepcopy(self.default)


class MongoModel:
    __tablename__ = ""
    id = Field()

    def __init__(self, **kwargs):
        for field in self.fields():
            if field in kwargs:
                setattr(self, field, kwargs[field])
            else:
                descriptor = getattr(type(self), field)
                setattr(self, field, descriptor.default_value())

    @classmethod
    def fields(cls) -> list[str]:
        fields = []
        for base in reversed(cls.__mro__):
            fields.extend(getattr(base, "__fields__", []))
        return list(dict.fromkeys(fields))

    def to_document(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.fields()}


def utcnow():
    return datetime.utcnow()
