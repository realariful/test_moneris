# -*- coding: utf-8 -*-

import os
import json
import logging
import requests
import werkzeug
from werkzeug import urls
import urllib.request
import lxml.html
from odoo import http
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.http import request
from odoo import SUPERUSER_ID
_logger = logging.getLogger(__name__)

def unescape(s):
    s = s.replace("&lt;", "<")
    s = s.replace("&gt;", ">")
    s = s.replace("&amp;", "&")
    s = s.replace("&quot;", "\"")
    return s

class MonerisController(http.Controller):
    _notify_url = '/payment/moneris/ipn/'
    _return_url = '/payment/moneris/dpn/'
    _cancel_url = '/payment/moneris/cancel/'

    def _get_return_url(self, **post):
        """ Extract the return URL from the data coming from moneris. """
        return_url = post.pop('return_url', '')
        if not return_url:
            t = unescape(post.pop('rvarret', '{}'))
            custom = json.loads(t)
            return_url = custom.get('return_url', '/')
        if not return_url:
            return_url = '/payment/shop/validate'
        _logger.info(str(return_url))
        return return_url

    def moneris_validate_data(self, **post):
        _logger.info("moneris_validate_data-->")
        _logger.info("post-->")
        _logger.info(post)
        res = False
        reference = post.get('rvaroid')
        tx = None
        if reference:
            tx_ids = request.env['payment.transaction'].search([('reference', '=', reference)])
            if tx_ids:
                tx = request.env['payment.transaction'].browse(tx_ids[0].id)
        if tx:
            _logger.info("---------------->")
            _logger.info(tx)
            _logger.info(tx.acquirer_id)
            _logger.info(tx.acquirer_id.state)
            _logger.info(tx and tx.acquirer_id and tx.acquirer_id.state or 'enabled')
            _logger.info("----------------")
            moneris_urls = request.env['payment.acquirer']._get_moneris_urls(tx and tx.acquirer_id and tx.acquirer_id.state or 'prod')
            _logger.info("moneris_urls--->")
            _logger.info(moneris_urls)
            validate_url = moneris_urls['moneris_auth_url']
            _logger.info("validate_url--->")
            _logger.info(validate_url)
        else:
            _logger.warning('Moneris: No order found')
            return res
        sid = tx.acquirer_id.moneris_psstore_id
        key = tx.acquirer_id.moneris_hpp_key
        new_post = dict(ps_store_id=sid, hpp_key=key, transactionKey=post.get('transactionKey'))
        _logger.info("new_post--->")
        _logger.info(str(new_post))
        urequest = requests.post(validate_url, new_post)
        _logger.info("urequest---------------->")
        _logger.info(str(urequest))
        try:
            _logger.info("urequest.text----------->")
            _logger.info(str(urequest.text))
        except Exception as e:
            _logger.info("Exception: " + str(e.args))
            _logger.info(str(urequest))
        new_response ={}
        try:
            file_name = open(post.get('response_order_id')+".html", "a+")
            file_name.write(urequest.text)
            file_name.close()
            tree = lxml.html.parse(post.get('response_order_id')+".html")
            root = tree.getroot()
            new_response ={}
            for form in root.xpath('//form'):
                for field in form.getchildren():
                    if 'name' in field.keys():
                        new_response[field.get('name')] = field.get('value')
            os.remove(post.get('response_order_id')+".html")
            _logger.info("HTML response-->")#Works in Test
            _logger.info(str(new_response))
        except Exception as e:
            # This does not work
            _logger.info(str(e.args))
            resp = urequest.text
            part = resp.split('<br>')
            new_response = dict([s.split(' = ') for s in part])#Error Here#
            _logger.info("New response from response-->")
            _logger.info(str(new_response))

        success = post.get('response_code')
        _logger.info("success-->")#Works in Test
        _logger.info(success)#Works in Test
        txn_key = ""
        _logger.info("New response-->")#Works in Test
        _logger.info(str(new_response))        
        _logger.info(str(new_response.get('status')))
        _logger.info(str(post.get('response_order_id')))
        try:
            if (int(success) < 50 and post.get('result') == '1'):
                # and
                #     new_response.get('response_code') is not 'null' and int(new_response.get('response_code')) < 50 and
                #     new_response.get('transactionKey') == post.get('transactionKey') and
                #     new_response.get('order_id') == post.get('response_order_id')
                # ):
                res = request.env['payment.transaction'].sudo().form_feedback(post, 'moneris')
                _logger.info('form_feedback--> '+ str(res))
                txn_key = post.get('transactionKey')
                if txn_key:
                    _logger.info('txn_key--> '+ str(txn_key))
            else:
                res = 'Moneris: answered INVALID on data verification: ' + new_response.get('status') + '/' + post.get('response_order_id')
            # else:
            #     res = 'Moneris: INVALID response on data verification: ' + new_response.get('status') + '/' + post.get('response_order_id')

        except ValueError:
            res = 'Moneris: answered INVALID on data verification: ' + new_response.get('status') + '/' + post.get('response_order_id')
        if txn_key != "":
            res = "status=approved&transactionKey={}".format(txn_key)
        _logger.info('-----------------------')
        _logger.info('res--> '+ str(res))
        _logger.info('-----------------------')
        return res

    @http.route('/payment/moneris/ipn/', type='http', auth='none', methods=['POST'], csrf=False)
    def moneris_ipn(self, **post):
        _logger.info("/payment/moneris/ipn/-->")
        res = self.moneris_validate_data(**post)
        _logger.info("return_url--> " + str(res))
        return werkzeug.utils.redirect('/moneris?{}'.format(res))

    @http.route('/payment/moneris/dpn', type='http', auth="none", methods=['POST'], csrf=False)
    def moneris_dpn(self, **post):
        _logger.info("moneris_dpn-->")
        return_url = self._get_return_url(**post)
        _logger.info("return_url--> " + str(return_url))
        if self.moneris_validate_data(**post):
            return werkzeug.utils.redirect(return_url)
        else:
            return werkzeug.utils.redirect(self._cancel_url)

    @http.route('/payment/moneris/cancel', type='http', auth="none", methods=['GET','POST'], csrf=False)
    def moneris_cancel(self, **post):
        _logger.info("moneris_cancel-->")
        reference = post.get('rvaroid')
        if reference:
            sales_order_obj = request.env['sale.order']
            so_ids = sales_order_obj.sudo().search([('name', '=', reference)])
            if so_ids:
                '''return_url = '/shop/payment/get_status/' + str(so_ids[0])'''
                so = sales_order_obj.browse(so_ids[0].id)
                # if so:
                #     '''
                #     tx.write({'state': 'cancel'})
                #     sale_order_obj.action_cancel(cr, SUPERUSER_ID, [order.id], context=request.context)
                #     '''
                #     '''
                #     tx_ids = request.registry['payment.transaction'].search(cr, uid, [('reference', '=', reference)], context=context)
                #     for tx in tx_ids:
                #         tx = request.registry['payment.transaction'].browse(cr, uid, tx, context=context)
                #         tx.write({'state': 'cancel'})
                #     sales_order_obj.write(cr, SUPERUSER_ID, [so.id], {'payment_acquirer_id': None,}, context=context)
                #     '''
                #     '''
                #     action_cancel(cr, SUPERUSER_ID, so.id, context=request.context)
                # '''
        msg = "/moneris?status=cancelled&"
        for key, value in post.items():
            msg += str(key)
            msg+= '='
            msg+= str(value)
            msg+='&'
        return werkzeug.utils.redirect(msg)

    @http.route('/moneris', type='http', auth='public', methods=['GET'], website=True)
    def moneris_status(self, **get):
        _logger.info("moneris_status-->")
        status = ''
        transactionKey = ''
        response_code = ''
        message = ''
        if 'status' in get:
            status = get['status']
        if 'transactionKey' in get:
            transactionKey = get['transactionKey']
        if 'response_code' in get:
            response_code = get['response_code']
        if 'message' in get:
            message = get['message']
        _logger.info(str(message))
        return request.render('payment_moneris_hosted.moneris_status', {'status': status, 'transactionKey': transactionKey, 'response_code': response_code, 'message': message})

