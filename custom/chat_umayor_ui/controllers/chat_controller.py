# -*- coding: utf-8 -*-
"""
Controlador HTTP del Chat UMayor
================================
Define las rutas públicas que consume el widget JavaScript:

  GET  /chat                  -> página dedicada del chat
  POST /chat/api/start        -> abre una sesión (devuelve token)
  POST /chat/api/send         -> envía un mensaje y recibe respuesta del bot
  POST /chat/api/products     -> lista productos disponibles
  POST /chat/api/sign_request -> dispara una solicitud de firma con Odoo Sign

Diseño:
- Las rutas /api/* son `type='jsonrpc'` para que el JS pueda hacer fetch
  con JSON puro y evitar problemas de CSRF.
- `auth='public'` permite que visitantes anónimos usen el bot.
- La respuesta del bot se delega al modelo de lógica (módulo del
  compañero) si está disponible; si no, se usa un fallback de eco
  para que la UI se pueda probar sin depender de IA.
"""
import logging
import time
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class ChatUMayorController(http.Controller):

    # -----------------------------------------------------------------
    # Página pública
    # -----------------------------------------------------------------
    @http.route('/chat', type='http', auth='public', website=True, sitemap=True)
    def chat_page(self, **kwargs):
        """Página dedicada con el chat a pantalla completa."""
        return request.render('chat_umayor_ui.chat_page_template', {})

    # -----------------------------------------------------------------
    # API: iniciar sesión
    # -----------------------------------------------------------------
    @http.route('/chat/api/start', type='jsonrpc', auth='public', csrf=False)
    def api_start(self, **kwargs):
        """Crea una sesión nueva y devuelve su token al frontend."""
        session = request.env['chat.umayor.session'].sudo().create({
            'state': 'active',
        })
        # Mensaje de bienvenida del bot
        request.env['chat.umayor.message'].sudo().create({
            'session_id': session.id,
            'role': 'bot',
            'content': _(
                'Hola, soy el asistente virtual de Banco UMayor. '
                '¿En qué producto financiero te puedo ayudar hoy?'
            ),
        })
        return {
            'token': session.token,
            'greeting': session.message_ids[-1].content,
        }

    # -----------------------------------------------------------------
    # API: enviar mensaje
    # -----------------------------------------------------------------
    @http.route('/chat/api/send', type='jsonrpc', auth='public', csrf=False)
    def api_send(self, token=None, message=None, **kwargs):
        """
        Recibe un mensaje del usuario, llama al motor de lógica del
        compañero (si existe) y devuelve la respuesta del bot.
        Mide y registra el tiempo de respuesta para el QA del Punto 6.
        """
        if not token or not message:
            return {'error': 'token_y_mensaje_requeridos'}

        Session = request.env['chat.umayor.session'].sudo()
        Message = request.env['chat.umayor.message'].sudo()

        session = Session.search([('token', '=', token)], limit=1)
        if not session:
            return {'error': 'sesion_no_encontrada'}

        # 1) Guardar mensaje del usuario
        Message.create({
            'session_id': session.id,
            'role': 'user',
            'content': message,
        })

        # 2) Generar respuesta (medir tiempo)
        t0 = time.monotonic()
        bot_text = self._delegate_to_core(session, message)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # 3) Guardar respuesta del bot
        Message.create({
            'session_id': session.id,
            'role': 'bot',
            'content': bot_text,
            'response_time_ms': elapsed_ms,
        })

        return {
            'reply': bot_text,
            'response_time_ms': elapsed_ms,
            'state': session.state,
        }

    def _delegate_to_core(self, session, user_message):
        """
        Hook de integración con el módulo de lógica del compañero
        (chat_umayor_core o nombre equivalente).

        Convención propuesta: el módulo del compañero registra un modelo
        `chat.umayor.core.engine` con un método `generate_reply(session, text)`
        que devuelve el texto de respuesta. Si no existe, hacemos un eco
        amigable para que la UI pueda demostrarse igual.
        """
        engine_model = request.env.get('chat.umayor.core.engine')
        if engine_model is not None:
            try:
                return engine_model.sudo().generate_reply(session, user_message)
            except Exception as e:
                _logger.warning(
                    'Fallo al delegar al motor de lógica: %s. '
                    'Usando fallback.', e,
                )

        # Fallback básico: eco con keywords muy simples para la demo
        text = (user_message or '').lower()
        if any(k in text for k in ('credito', 'crédito', 'préstamo', 'prestamo')):
            return _(
                'Tenemos créditos de consumo desde 1.000.000 hasta 30.000.000 CLP. '
                '¿Quieres que te muestre las condiciones?'
            )
        if 'tarjeta' in text:
            return _(
                'Manejamos tarjetas Clásica, Gold y Platinum. '
                '¿Cuál te interesa conocer?'
            )
        if any(k in text for k in ('firmar', 'firma', 'contratar')):
            return _(
                'Perfecto. Para firmar el contrato necesito tu correo '
                'electrónico. ¿Me lo puedes compartir?'
            )
        return _(
            'Recibí tu mensaje: «%s». ¿Te gustaría conocer nuestros créditos, '
            'tarjetas o cuentas de ahorro?'
        ) % user_message

    # -----------------------------------------------------------------
    # API: catálogo de productos
    # -----------------------------------------------------------------
    @http.route('/chat/api/products', type='jsonrpc', auth='public', csrf=False)
    def api_products(self, **kwargs):
        """Devuelve los productos financieros activos para mostrarlos como chips."""
        products = request.env['chat.umayor.product'].sudo().search(
            [('active', '=', True)]
        )
        return [{
            'id': p.id,
            'code': p.code,
            'name': p.name,
            'short_description': p.short_description or '',
        } for p in products]

    # -----------------------------------------------------------------
    # API: solicitar firma digital (PUNTO 4 - Integración con Odoo Sign)
    # -----------------------------------------------------------------
    @http.route('/chat/api/sign_request', type='jsonrpc', auth='public', csrf=False)
    def api_sign_request(self, token=None, product_code=None,
                         signer_name=None, signer_email=None, **kwargs):
        """
        Crea una solicitud de firma en Odoo Sign para el producto que
        eligió el cliente y devuelve la URL para que firme.

        Comportamiento defensivo:
        - Si el módulo `sign` NO está instalado, devuelve un mensaje claro
          y NO falla, para que el flujo de la UI siga siendo demostrable.
        - Si el producto no tiene plantilla configurada, también lo informa.
        """
        if not all([token, product_code, signer_name, signer_email]):
            return {'error': 'datos_incompletos'}

        session = request.env['chat.umayor.session'].sudo().search(
            [('token', '=', token)], limit=1
        )
        if not session:
            return {'error': 'sesion_no_encontrada'}

        product = request.env['chat.umayor.product'].sudo().search(
            [('code', '=', product_code)], limit=1
        )
        if not product:
            return {'error': 'producto_no_encontrado'}

        # Comprobamos que el módulo Odoo Sign esté instalado
        SignTemplate = request.env.get('sign.template')
        SignRequest = request.env.get('sign.request')
        if SignTemplate is None or SignRequest is None:
            _logger.info(
                'Módulo Odoo Sign no instalado. La solicitud para %s '
                'queda registrada en modo simulado.',
                signer_email,
            )
            session.write({'state': 'awaiting_signature', 'product_id': product.id})
            return {
                'mode': 'stub',
                'message': _(
                    'Solicitud de firma registrada en modo demo. '
                    'Instale el módulo "sign" para enviar el contrato real.'
                ),
            }

        if not product.sign_template_ref:
            return {
                'error': 'sin_plantilla',
                'message': _('Este producto aún no tiene plantilla de contrato configurada.'),
            }

        # Buscar o crear el partner del firmante
        Partner = request.env['res.partner'].sudo()
        partner = Partner.search([('email', '=', signer_email)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': signer_name,
                'email': signer_email,
            })

        # Crear la solicitud de firma usando la plantilla del producto
        try:
            template = product.sign_template_ref
            # En Odoo 19 se crea sign.request enlazando los signer_ids al template
            sign_request = SignRequest.sudo().create({
                'template_id': template.id,
                'reference': _('Contrato %s - %s') % (product.name, partner.name),
                'request_item_ids': [
                    (0, 0, {
                        'partner_id': partner.id,
                        'role_id': template.sign_item_ids.responsible_id[:1].id
                                   if template.sign_item_ids else False,
                    }),
                ],
            })
            session.write({
                'state': 'awaiting_signature',
                'product_id': product.id,
                'sign_request_ref': '%s,%s' % ('sign.request', sign_request.id),
                'partner_id': partner.id,
                'visitor_email': signer_email,
                'visitor_name': signer_name,
            })

            # URL pública para firmar (Odoo Sign genera un access_token)
            access_token = sign_request.request_item_ids[:1].access_token
            sign_url = '/sign/document/%s/%s' % (sign_request.id, access_token)

            return {
                'mode': 'live',
                'sign_request_id': sign_request.id,
                'sign_url': sign_url,
                'message': _('Te enviamos el contrato para firmar.'),
            }
        except Exception as e:
            _logger.exception('Error al crear solicitud de firma')
            return {'error': 'sign_error', 'message': str(e)}