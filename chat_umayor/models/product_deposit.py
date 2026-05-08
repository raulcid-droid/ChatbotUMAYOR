"""Modelo de producto Depósito a Plazo.

Chile, valores ficticios académicos. La tasa anual es fija por tramo
de plazo (30/60/90/180/365 días). El interés es **simple**
(``amount * rate * term_days / 360``) y se redondea a entero CLP.

Expone los mismos dos métodos puros que ``chat_umayor.product.soap``:
``_validate`` y ``_calculate``. Las instancias singleton viven en
``data/products.xml``.
"""

from odoo import fields, models


# Tasa anual por tramo de plazo (en fracción, no porcentaje).
# Orden: ascendente por plazo. Ficticio, valores académicos.
_RATES_BY_TERM: dict[int, float] = {
    30: 0.03,
    60: 0.035,
    90: 0.04,
    180: 0.045,
    365: 0.05,
}

# Rango aceptado para ``amount`` (CLP).
_MIN_AMOUNT = 50_000
_MAX_AMOUNT = 100_000_000

# Convención de cálculo: año comercial de 360 días (estándar banca
# para depósitos a plazo en Chile).
_DAYS_IN_YEAR = 360


class ChatUmayorProductDeposit(models.Model):
    """Producto Depósito a Plazo con tasa fija por tramo."""

    _name = "chat_umayor.product.deposit"
    _description = "Chat UMayor — Producto Depósito a Plazo"

    name = fields.Char(
        string="Nombre",
        required=True,
        default="Depósito a Plazo",
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
        """Valida el payload de ``product_data`` para Depósito.

        Args:
            product_data: Dict con ``amount`` y ``term_days``.

        Returns:
            Dict ``{campo: mensaje}`` con las violaciones. Vacío si
            todo OK.
        """
        errors: dict[str, str] = {}

        if not isinstance(product_data, dict):
            return {"product_data": "Debe ser un objeto con los datos del depósito."}

        amount = product_data.get("amount")
        # ``bool`` es subclase de ``int`` en Python; lo descartamos
        # explícitamente para que ``True``/``False`` no pasen como
        # monto válido.
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            errors["amount"] = "El monto debe ser numérico."
        elif amount < _MIN_AMOUNT or amount > _MAX_AMOUNT:
            errors["amount"] = (
                f"Debe estar entre {_MIN_AMOUNT:,} y {_MAX_AMOUNT:,} CLP."
            )

        term = product_data.get("term_days")
        if isinstance(term, bool) or not isinstance(term, int):
            errors["term_days"] = "El plazo debe ser un número entero de días."
        elif term not in _RATES_BY_TERM:
            allowed = ", ".join(str(k) for k in sorted(_RATES_BY_TERM))
            errors["term_days"] = f"Plazo inválido. Opciones: {allowed} días."

        return errors

    # ------------------------------------------------------------------
    # Cálculo
    # ------------------------------------------------------------------

    def _calculate(self, product_data: dict) -> dict:
        """Calcula interés simple y total al vencimiento.

        Fórmula: ``interest = amount * rate * term_days / 360``.
        Redondeo a entero CLP (``round``). Asume que ``product_data``
        ya pasó por ``_validate``.

        Args:
            product_data: Dict con ``amount`` y ``term_days`` válidos.

        Returns:
            Dict con ``principal``, ``interest``, ``total_at_maturity``,
            ``rate`` (fracción), ``term_days`` y ``currency``.
        """
        self.ensure_one()
        amount = product_data["amount"]
        term_days = product_data["term_days"]
        rate = _RATES_BY_TERM[term_days]

        interest = round(amount * rate * term_days / _DAYS_IN_YEAR)
        principal = round(amount)
        total = principal + interest

        return {
            "principal": principal,
            "interest": interest,
            "total_at_maturity": total,
            "rate": rate,
            "term_days": term_days,
            "currency": self.currency or "CLP",
        }
