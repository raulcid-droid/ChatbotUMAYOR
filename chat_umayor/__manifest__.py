{
    'name': 'Chat UMayor',
    'version': '19.0.1.0.0',
    'summary': 'Asistente Virtual Banco UMayor',
    'author': 'UMayor',
    'category': 'Website',
    'depends': ['website'],
    'data': [
        'views/assets.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'chat_umayor/static/src/css/chatbot.css',
            'chat_umayor/static/src/css/chatbot_extras.css',
            'chat_umayor/static/src/js/chatbot.js',
            'chat_umayor/static/src/js/chatbot_extras.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
