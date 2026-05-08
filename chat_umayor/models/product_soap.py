"""Modelo de producto SOAP (Seguro Obligatorio de Accidentes Personales).

Chile, valores ficticios académicos. La prima es plana por tipo de
vehículo; no hay cálculo por cilindrada, zona ni antigüedad. El modelo
expone dos métodos puros:

- ``_validate(product_data)``: valida los campos del formulario y
  devuelve un dict ``{campo: mensaje}`` con las violaciones. Vacío si
  todo OK.
- ``_calculate(product_data)``: calcula la prima a partir del tipo de
  vehículo y devuelve un dict estable consumido por ``/submit_data``.

Las instancias singleton viven en ``data/products.xml``.
"""

import datetime
import re

from odoo import fields, models


# Regex de patente chilena (moderna ``BCDF12`` y legacy ``AB1234``).
# 2 letras obligatorias + 2 alfanuméricos + 2 dígitos.
_PLATE_REGEX = re.compile(r"^[A-Z]{2}[A-Z0-9]{2}[0-9]{2}$")

# Límites para ``vehicle_year``. El máximo se recalcula en runtime
# con ``datetime.date.today().year + 1`` para aceptar modelos del
# próximo año (es habitual en catálogos).
_MIN_YEAR = 1950


class ChatUmayorProductSoap(models.Model):
    """Producto SOAP con tarifa plana por tipo de vehículo."""

    _name = "chat_umayor.product.soap"
    _description = "Chat UMayor — Producto SOAP"

    # Tarifa anual en pesos chilenos (CLP), ficticia. Orden importa:
    # los tests iteran este dict.
    _TARIFFS: dict[str, int] = {
        "particular": 7990,
        "moto": 3990,
        "comercial": 14990,
        "taxi": 24990,
    }

    name = fields.Char(
        string="Nombre",
        required=True,
        default="SOAP",
        help="Nombre visible del producto.",
    )

    currency = fields.Char(
        string="Moneda",
        required=True,
        default="CLP",
        help="Código de moneda ISO-4217 para los montos devueltos.",
    )

    # ------------------------------------------------------------------
    # Validación
    # ------------------------------------------------------------------

    def _validate(self, product_data: dict) -> dict[str, str]:
        """Valida el payload de ``product_data`` para SOAP.

        Args:
            product_data: Dict con ``vehicle_plate``, ``vehicle_year``
                y ``vehicle_type``.

        Returns:
            Dict ``{campo: mensaje}`` con las violaciones. Vacío si
            todo es válido. El orden de inserción es el de validación.
        """
        errors: dict[str, str] = {}

        if not isinstance(product_data, dict):
            return {"product_data": "Debe ser un objeto con los datos del vehículo."}

        plate = product_data.get("vehicle_plate")
        if not plate or not isinstance(plate, str):
            errors["vehicle_plate"] = "La patente es obligatoria."
        else:
            normalized = plate.strip().upper().replace(" ", "").replace("-", "")
            if not _PLATE_REGEX.match(normalized):
                errors["vehicle_plate"] = (
                    "Patente con formato inválido (ej: BCDF12 o AB1234)."
                )

        year = product_data.get("vehicle_year")
        max_year = datetime.date.today().year + 1
        if not isinstance(year, int) or isinstance(year, bool):
            errors["vehicle_year"] = "El año debe ser un número entero."
        elif year < _MIN_YEAR or year > max_year:
            errors["vehicle_year"] = (
                f"El año debe estar entre {_MIN_YEAR} y {max_year}."
            )

        vtype = product_data.get("vehicle_type")
        if vtype not in self._TARIFFS:
            allowed = ", ".join(sorted(self._TARIFFS.keys()))
            errors["vehicle_type"] = f"Tipo de vehículo inválido. Opciones: {allowed}."

        return errors

    # ------------------------------------------------------------------
    # Cálculo
    # ------------------------------------------------------------------

    def _calculate(self, product_data: dict) -> dict:
        """Calcula la prima para el vehículo dado.

        Asume que ``product_data`` ya pasó por ``_validate`` y los
        campos son válidos. Si se llama con datos inválidos, lanza
        ``KeyError`` (es un bug del llamador, no un error de usuario).

        Args:
            product_data: Dict con al menos ``vehicle_type``.

        Returns:
            Dict ``{"premium": int, "currency": "CLP",
            "vehicle_type": str}`` consumido por ``/submit_data``.
        """
        self.ensure_one()
        vtype = product_data["vehicle_type"]
        premium = self._TARIFFS[vtype]
        return {
            "premium": premium,
            "currency": self.currency or "CLP",
            "vehicle_type": vtype,
        }
