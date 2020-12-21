from typing import Any, Dict, Optional, Tuple

from cuenca_validations.typing import DictStrAny
from cuenca_validations.validators import sanitize_item
from rom import Column, Model, PrimaryKey

from agave.exc import ObjectDoesNotExist
from agave.models.base import BaseModel


class String(Column):
    """
    No utilizo la clase String de rom porque todo lo maneja en bytes
    codificado en latin-1.
    """

    _allowed = str

    def _to_redis(self, value):
        return value.encode('utf-8')

    def _from_redis(self, value):
        return value.decode('utf-8')


def redis_to_dit(obj, exclude_fields: list = None) -> dict:
    excluded = ['o_id']
    response = {
        key: sanitize_item(value)
        for key, value in obj._data.items()
        if key not in excluded
    }
    return response


class RedisModel(BaseModel, Model):
    meta = {'allow_inheritance': True}
    o_id = PrimaryKey()  # Para que podamos usar `id` en los modelos

    def dict(self) -> DictStrAny:
        return self._dict(redis_to_dit)

    @classmethod
    def retrieve(cls, id: str, user_id: Optional[str] = None):
        params = dict(id=id)
        if user_id:
            params['user_id'] = user_id
        obj = cls.query.filter(**params).first()
        if not obj:
            raise ObjectDoesNotExist
        return obj

    @classmethod
    def count(cls, filters: Any) -> int:
        count = cls.query.filter(**filters).count()
        return count

    @classmethod
    def filter_limit(cls, filters: Dict, limit: int) -> Tuple[Any, bool]:
        items = (
            cls.query.filter(**filters).order_by('-created_at').limit(0, limit)
        )
        has_more = items.limit(0, limit + 1).count() > limit
        items = list(items)
        return items, has_more