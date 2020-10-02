# -*- coding: utf-8 -*-

{
    'name': 'Moneris Payment Acquirer (Hosted)',
    'version': '13.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Payment Acquirer: Moneris Implementation (Hosted)',
    'description': """Moneris Payment Acquirer (Hosted)""",
    'author': "Syncoria Inc.",
    'website': "https://www.syncoria.com",
    'company': 'Syncoria Inc.',
    'maintainer': 'Syncoria Inc.',
    'depends': ['payment'],
    'images': [
        'static/description/banner.png',
    ],
    'data': [
        'views/payment_moneris_templates.xml',
        'views/payment_views.xml',
        'data/moneris.xml',
        'views/response_status.xml',
    ],
    'price': 400,
    'currency': 'USD',
    'license': 'OPL-1',
    'support': "support@syncoria.com",
    'installable': True,
    'application': False,
    'auto_install': False,
    #'uninstall_hook': 'uninstall_hook',
}
