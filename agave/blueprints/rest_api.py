from typing import Any, Optional, Type
from urllib.parse import urlencode

from chalice import Blueprint, NotFoundError, Response
from cuenca_validations.types import QueryParams
from pydantic import BaseModel, ValidationError

from .decorators import copy_attributes


class RestApiBlueprint(Blueprint):
    def get(self, path: str, **kwargs):
        return self.route(path, methods=['GET'], **kwargs)

    def post(self, path: str, **kwargs):
        return self.route(path, methods=['POST'], **kwargs)

    def patch(self, path: str, **kwargs):
        return self.route(path, methods=['PATCH'], **kwargs)

    def delete(self, path: str, **kwargs):
        return self.route(path, methods=['DELETE'], **kwargs)

    @property
    def current_user_id(self):
        return self.current_request.user_id

    def user_id_filter_required(self):
        """
        This method is required to be implemented with your own business logic.
        You are responsible of determining when `user_id` filter is required.
        """
        raise NotImplementedError(
            'this method should be override'
        )  # pragma: no cover

    def validate(self, validation_type: Type[BaseModel]):
        """This decorator validate the request body using a custom pydantyc model
        If validation fails return a BadRequest response with details

        @app.validate(MyPydanticModel)
        def my_method(request: MyPydanticModel):
            ...
        """

        def decorator(func):
            def wrapper(*args, **kwargs):
                try:
                    request = validation_type(**self.current_request.json_body)
                except ValidationError as e:
                    return Response(e.json(), status_code=400)
                return func(*args, request, **kwargs)

            return wrapper

        return decorator

    def resource(self, path: str):
        """Decorator to transform a class in Chalice REST endpoints

        @app.resource('/my_resource')
        class Items(Resource):
            model = MyMongoModel
            query_validator = MyPydanticModel

            def create(): ...
            def delete(id): ...
            def retrieve(id): ...
            def get_query_filter(): ...

        This implementation create the following endpoints

        POST /my_resource
        PATCH /my_resource
        DELETE /my_resource/id
        GET /my_resource/id
        GET /my_resource
        """

        def wrapper_resource_class(cls):
            """Wrapper for resource class
            :param cls: Resoucre class
            :return:
            """

            """ POST /resource
            Create a chalice endpoint using the method "create"
            If the method receive body params decorate it with @validate
            """
            if hasattr(cls, 'create'):
                route = self.post(path)
                route(cls.create)

            """ DELETE /resource/{id}
            Use "delete" method (if exists) to create the chalice endpoint
            """
            if hasattr(cls, 'delete'):
                route = self.delete(path + '/{id}')
                route(cls.delete)

            """ PATCH /resource/{id}
            Enable PATCH method if Resource.update method exist. It validates
            body data using `Resource.update_validator` but update logic is
            completely your responsibility.
            """
            if hasattr(cls, 'update'):
                route = self.patch(path + '/{id}')

                @copy_attributes(cls)
                def update(id: str):
                    params = self.current_request.json_body or dict()
                    try:
                        data = cls.update_validator(**params)
                        model = cls.model.retrieve(cls, id=id)
                    except ValidationError as e:
                        return Response(e.json(), status_code=400)
                    except Exception:
                        raise NotFoundError('Not valid id')
                    else:
                        return cls.update(model, data)

                route(update)

            @self.get(path + '/{id}')
            @copy_attributes(cls)
            def retrieve(id: str):
                """GET /resource/{id}
                :param id: Object Id
                :return: Model object

                If exists "retrieve" method return the result of that, else
                use "id" param to retrieve the object of type "model" defined
                in the decorated class.

                The most of times this implementation is enough and is not
                necessary define a custom "retrieve" method
                """
                if hasattr(cls, 'retrieve'):
                    # at the moment, there are no resources with a custom
                    # retrieve method
                    return cls.retrieve(id)  # pragma: no cover
                try:
                    data = cls.model.retrieve(cls, id=id)
                    if self.user_id_filter_required():
                        data = cls.model.retrieve(
                            cls, id=id, user_id=self.current_user_id
                        )
                except Exception:
                    raise NotFoundError('Not valid id')
                return data.dict()

            @self.get(path)
            @copy_attributes(cls)
            def query():
                """GET /resource
                Method for queries in resource. Use "query_validator" type
                defined in decorated class to validate the params.

                The "get_query_filter" method defined in decorated class
                should provide the way that the params are used to filter data

                If param "count" is True return the next response
                {
                    count:<count>
                }

                else the response is like this
                {
                    items = [{},{},...]
                    next_page = <url_for_next_items>
                }
                """
                params = self.current_request.query_params or dict()
                try:
                    query_params = cls.query_validator(**params)
                except ValidationError as e:
                    return Response(e.json(), status_code=400)
                # Set user_id request as query param
                if self.user_id_filter_required():
                    query_params.user_id = self.current_user_id
                filters = cls.get_query_filter(query_params)
                if query_params.count:
                    return _count(filters)
                return _all(query_params, filters)

            def _count(filters: Any):
                count = cls.model.count(cls, filters)
                return dict(count=count)

            def _all(query: QueryParams, filters: Any):
                if query.limit:
                    limit = min(query.limit, query.page_size)
                    query.limit = max(0, query.limit - limit)  # type: ignore
                else:
                    limit = query.page_size
                items, items_limit = cls.model.filter_limit(
                    cls, filters, limit
                )
                items = list(items)

                has_more: Optional[bool] = None
                if wants_more := query.limit is None or query.limit > 0:
                    # only perform this query if it's necessary
                    has_more = items_limit

                next_page_uri: Optional[str] = None
                if wants_more and has_more:
                    query.created_before = items[-1].created_at.isoformat()
                    path = self.current_request.context['resourcePath']
                    params = query.dict()
                    if self.user_id_filter_required():
                        params.pop('user_id')
                    next_page_uri = f'{path}?{urlencode(params)}'
                return dict(
                    items=[i.dict() for i in items],  # type: ignore
                    next_page_uri=next_page_uri,
                )

            return cls

        return wrapper_resource_class
