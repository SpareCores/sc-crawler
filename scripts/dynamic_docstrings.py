import ast
import inspect
from griffe import Docstring, Extension, Object, ObjectNode, get_logger, dynamic_import

logger = get_logger(__name__)


# https://mkdocstrings.github.io/griffe/extensions/#full-example
class DynamicDocstrings(Extension):
    def on_instance(self, node: ast.AST | ObjectNode, obj: Object) -> None:
        if isinstance(node, ObjectNode):
            return  # skip runtime objects, their docstrings are already right

        if str(obj.relative_filepath) != "src/sc_crawler/schemas.py":
            return

        # import object to get its evaluated docstring
        try:
            runtime_obj = dynamic_import(obj.path)
            docstring = runtime_obj.__doc__
        except ImportError:
            logger.debug(f"Could not get dynamic docstring for {obj.path}")
            return
        except AttributeError:
            logger.debug(f"Object {obj.path} does not have a __doc__ attribute")
            return

        # update the object instance with the evaluated docstring
        try:
            docstring = inspect.cleandoc(docstring)
            if obj.docstring:
                obj.docstring.value = docstring
            else:
                obj.docstring = Docstring(docstring, parent=obj)
        except Exception as e:
            logger.debug(f"Could not set docstring: {str(e)}")
