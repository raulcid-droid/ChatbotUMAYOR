{
    'name': 'Chat UMayor',
    'version': '19.0.1.0.0',
    'summary': 'Asistente Virtual Banco RRJ',
    'author': 'UMayor',
    'category': 'Website',
    'depends': ['website'],
    'data': [
        'views/assets.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'chat_umayor/static/src/css/chatbot.css',
            'chat_umayor/static/src/js/chatbot.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
