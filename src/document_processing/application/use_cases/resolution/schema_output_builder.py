from __future__ import annotations

from typing import Any

from document_processing.domain.contracts.schema import is_type_descriptor
from document_processing.domain.layouts.paths import get_nested_value, parse_mapping_path, set_nested_value

class SchemaOutputBuilderMixin:
    @staticmethod
    def _build_schema_template(contract_node: Any) -> Any:
        if isinstance(contract_node, dict):
            return {
                key: SchemaOutputBuilderMixin._build_schema_template(value)
                for key, value in contract_node.items()
            }
        if isinstance(contract_node, list):
            return []
        # O contrato usa descritores como ``string`` e ``number`` para campos
        # que precisam ser resolvidos. Literais, por outro lado, sao valores
        # semanticos estaveis do proprio contrato (por exemplo, unidade e tipo
        # de operacao) e devem existir no schema sem depender do layout.
        if is_type_descriptor(contract_node):
            return None
        return contract_node

    @staticmethod
    def _parse_mapping_path(mapping_path: str) -> list[dict[str, str | tuple[str, str]]]:
        try:
            return parse_mapping_path(mapping_path)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    def _set_schema_value(
        self,
        *,
        target: dict[str, Any],
        contract_template: Any,
        mapping_path: str,
        value: Any,
    ) -> None:
        tokens = self._parse_mapping_path(mapping_path)
        current: Any = target
        current_contract: Any = contract_template

        for index, token in enumerate(tokens):
            field = str(token["field"])
            selector = token.get("selector")
            is_last = index == len(tokens) - 1

            if not isinstance(current, dict):
                raise RuntimeError(f"Caminho nao compativel com schema_saida do contrato: {mapping_path}")

            if selector is None:
                if not self._contract_has_field(current_contract, field):
                    return
                if is_last:
                    current[field] = value
                    return
                child_contract = self._contract_child_template(current_contract, field)
                if field not in current or current[field] is None:
                    current[field] = self._build_schema_template(child_contract)
                current = current[field]
                current_contract = child_contract
                continue

            if not self._contract_has_field(current_contract, field):
                return
            array_contract = self._contract_child_template(current_contract, field)
            item_contract = array_contract[0] if isinstance(array_contract, list) and array_contract else {}
            if not isinstance(current.get(field), list):
                current[field] = []
            item = self._find_or_create_schema_array_item(
                items=current[field],
                item_contract=item_contract,
                selector=selector,
            )
            if is_last:
                if isinstance(item, dict) and isinstance(value, dict):
                    item.update(value)
                else:
                    item = value
                return
            current = item
            current_contract = item_contract

    @staticmethod
    def _contract_child_template(contract_node: Any, field: str) -> Any:
        if isinstance(contract_node, dict):
            return contract_node.get(field)
        return None

    @staticmethod
    def _contract_has_field(contract_node: Any, field: str) -> bool:
        return isinstance(contract_node, dict) and field in contract_node

    def _find_or_create_schema_array_item(
        self,
        *,
        items: list[Any],
        item_contract: Any,
        selector: str | tuple[str, str],
    ) -> dict[str, Any]:
        selector_key, selector_value = selector
        for item in items:
            if not isinstance(item, dict):
                continue
            selectors = item.get("__selectors__")
            if isinstance(selectors, dict) and selectors.get(selector_key) == selector_value:
                return item
            if get_nested_value(item, selector_key) == selector_value:
                return item

        item = self._build_schema_template(item_contract)
        if not isinstance(item, dict):
            item = {}
        item["__selectors__"] = {selector_key: selector_value}
        if "." in selector_key:
            set_nested_value(item, selector_key, selector_value)
        elif selector_key in item and item[selector_key] is None:
            item[selector_key] = selector_value
        items.append(item)
        return item

    def _strip_internal_schema_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._strip_internal_schema_metadata(item)
                for key, item in value.items()
                if key != "__selectors__"
            }
        if isinstance(value, list):
            return [self._strip_internal_schema_metadata(item) for item in value]
        return value
