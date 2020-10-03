# -*- coding: utf-8 -*-

# import os
import json
import logging
import pprint

import requests
import werkzeug
from werkzeug import urls

import lxml.html
import xmltodict

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
        _logger.info(request.session)
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
        """ 
        Moneris IPN: three steps validation to ensure data correctness
         - step 1: return an empty HTTP 200 response -> will be done at the end
           by returning ''
         - step 2: POST the complete, unaltered message back to Moneris (preceded
           by cmd=_notify-validate), with same encoding
         - step 3: moneris send either VERIFIED or INVALID (single word)

        Once data is validated, process it. 
        """
        _logger.info("moneris_validate_data-->")
        res = False
        _logger.info("----------post---------------")
        _logger.info(post)
        reference = post.get('rvaroid')
        tx = None
        if reference:
            tx_ids = request.env['payment.transaction'].sudo().search([('reference', '=', reference)])
            if tx_ids:
                tx = request.env['payment.transaction'].sudo().browse(tx_ids[0].id)
        _logger.info("----------tx & ref ---------------")
        _logger.info(str(tx) + ", " + str(reference))
        if tx:
            _logger.info(tx)
            _logger.info("TX Date--> " +  str(tx.date))
            _logger.info(tx.acquirer_id)
            _logger.info(str(tx.acquirer_id.state))
            _logger.info(tx and tx.acquirer_id and tx.acquirer_id.state or 'enabled')
            moneris_urls = request.env['payment.acquirer']._get_moneris_urls(tx and tx.acquirer_id and tx.acquirer_id.state or 'prod')
            validate_url = moneris_urls['moneris_auth_url']
            _logger.info("moneris_urls---> " + str(moneris_urls))
            _logger.info("validate_url---> " + str(validate_url))
        else:
            _logger.warning('Moneris: No order found')
            return res

        sid = tx.acquirer_id.moneris_psstore_id
        _logger.info(sid)
        key = tx.acquirer_id.moneris_hpp_key
        _logger.info(key)
        # Check for gift cards 
        
        # 
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
            # Convert Xml to json
            tree = lxml.html.fromstring(urequest.content)
            new_response = {}
            form_values = tree.xpath('//input')
            for field in form_values:
                if field.name != None:
                    new_response[field.name] = field.value
            _logger.info("HTML response-->")
            _logger.info(str(new_response))
        except Exception as e:
            _logger.warning(str(e.args))
            raise ValidationError(str(e.args))

        success = post.get('response_code') if 'gift_card' not in post else post['gift_card'].get('response_code')
        if 'gift_card' in post:
            post = dict(post)
            gift_card = dict(post['gift_card'])
            post.update(gift_card)
            _logger.info("New Post for Gift Card--> " + str(post))
        
        _logger.info("success--> " + str(success))
        txn_key = ""
        _logger.info("New response-->")
        _logger.info(str(new_response))        
        _logger.info(str(new_response.get('status')))
        _logger.info(str(post.get('response_order_id')))
        try:
            if success and new_response.get('response_code'):
                _logger.info(str(success) + "," + str(new_response.get('response_code')))
            if (int(success) < 50 and post.get('result') == '1'):
                #     and new_response.get('response_code') is not 'null' and int(new_response.get('response_code')) < 50 and
                #     new_response.get('transactionKey') == post.get('transactionKey') and
                #     new_response.get('order_id') == post.get('response_order_id')
                # ):
                _logger.info('Moneris: validated data')
                res = request.env['payment.transaction'].sudo().form_feedback(post, 'moneris')
                _logger.info('form_feedback--> '+ str(res))
                txn_key = post.get('transactionKey')
                if txn_key:
                    _logger.info('txn_key--> '+ str(txn_key))
            else:
                res = 'Moneris: answered INVALID on data verification: ' + new_response.get('status') + '/' + post.get('response_order_id')

        except ValueError:
            res = 'Moneris: answered INVALID on data verification: ' + new_response.get('status') + '/' + post.get('response_order_id')

        if txn_key != "":
            res = "status=approved&transactionKey={}".format(txn_key)
        _logger.info('-----------------------')
        _logger.info('res--> '+ str(res))

        if 'transactionKey' in res:
            try:
                _logger.info("Before request.session------------>")
                _logger.info(request.session)

                session = dict(request.session)
                if tx:
                    order_id_new = tx.sale_order_ids
                    if len(order_id_new) == 0:
                        order_id_new = request.env['sale.order'].sudo().search([('name','=',post.get('response_order_id').split("-")[0])], limit=1)
                    _logger.info("\n tx" + ": " + str(tx) + 
                            "\n tx.sale_order_ids: " + str(tx.sale_order_ids) + \
                            "\n tx.sale_order_ids_nbr: " + str(tx.sale_order_ids_nbr) + \
                            "\n tx.response_order_id: " + str(post.get('response_order_id')) + \
                            "\n order_id_new: " + str(order_id_new) 
                    )

                    _logger.info(order_id_new)
                    if '__payment_tx_ids__' not in session:
                        _logger.info('__payment_tx_ids__')
                        try:
                            request.session['__payment_tx_ids__'] = []
                            request.session['__payment_tx_ids__'].append(int(tx.id))
                            _logger.info("TX Appending")
                        except Exception as e:
                            _logger.info("Excception __payment_tx_ids__: " + str(e.args))
                            request.session['__payment_tx_ids__'] = (int(tx.id))
                            _logger.info(request.session['__payment_tx_ids__'])

                    if '__payment_tx_ids__' in session:
                        _logger.info(type(request.session['__payment_tx_ids__']))
                        _logger.info(request.session['__payment_tx_ids__'])
                        if tx.id not in session['__payment_tx_ids__']:
                            try:
                                request.session['__payment_tx_ids__'].append(int(tx.id))
                                _logger.info("TX Appending")
                            except Exception as e:
                                _logger.info("Excception __payment_tx_ids__: " + str(e.args))
                                request.session['__payment_tx_ids__'] = (int(tx.id))
                                _logger.info("TX Tuple Add")

                    if '__website_sale_last_tx_id' in session:
                        try:
                            if tx.id  != session['__website_sale_last_tx_id']:
                                request.session['__website_sale_last_tx_id'] = int(tx.id)
                            _logger.info(type(session['__website_sale_last_tx_id']))
                            _logger.info(request.session['__website_sale_last_tx_id'])
                        except Exception as e:
                            if tx.id  != session['__website_sale_last_tx_id']:
                                request.session['__website_sale_last_tx_id'] = (int(tx.id))
                            _logger.info("Excception __website_sale_last_tx_id: " + str(e.args))

                    if '__website_sale_last_tx_id' not in session:
                        try:
                            _logger.info("---------------->") 
                            request.session['__website_sale_last_tx_id'] = (int(tx.id))
                            _logger.info(request.session['__website_sale_last_tx_id'])   
                        except Exception as e:
                            request.session['__website_sale_last_tx_id'] = int(tx.id)
                            _logger.warning("Error __website_sale_last_tx--> " + str(e.args))
                        _logger.info("---------------->")                             

                    if 'sale_order_id' not in session:
                        try:
                            _logger.info("sale_order_id---------------->") 
                            request.session['sale_order_id'] = int(order_id_new.id)
                            _logger.info(request.session['__website_sale_last_tx_id'])   
                            _logger.info(type(request.session['sale_order_id']))
                            _logger.info(request.session['sale_order_id'])
                        except Exception as e:
                            request.session['sale_order_id'] = (int(order_id_new.id))
                            _logger.info("sale_order_id-->"+str(e.args))


                    if 'sale_last_order_id' not in session:
                        try:
                            _logger.info("sale_last_order_id---------------->") 
                            request.session['sale_last_order_id'] = int(order_id_new.id)
                            _logger.info(type(request.session['sale_last_order_id']))
                            _logger.info(request.session['sale_last_order_id'])
                        except Exception as e:
                            request.session['sale_last_order_id'] =  (int(order_id_new.id))
                            _logger.info("sale_last_order_id-->"+str(e.args))

                    # _logger.info(tx.sale_order_ids)
                    # _logger.info(tx.sale_order_ids_nbr)
                    # _logger.info(post.get('response_order_id'))
                    # order_id = request.env['sale.order'].sudo().search([('origin','=',post.get('response_order_id').split("-")[0])])
                    # order_id_new = request.env['sale.order'].sudo().search([('name','=',post.get('response_order_id').split("-")[0])])
                    # _logger.info(order_id_new)
                    # ----------------------Community Edition-------------------------------------------------
                    # if '__payment_tx_ids__' in session:
                    #     _logger.info(session['__payment_tx_ids__'])
                    #     if tx.id not in session['__payment_tx_ids__']:
                    #         request.session['__payment_tx_ids__'].append(int(tx.id))
                    # if '__website_sale_last_tx_id' in session:
                    #     if tx.id  != session['__website_sale_last_tx_id']:
                    #         request.session['__website_sale_last_tx_id'] = int(tx.id)
                    # if '__payment_tx_ids__' not in session:
                    #     request.session['__payment_tx_ids__'] = []
                    #     request.session['__payment_tx_ids__'].append(int(tx.id))
                    # if '__website_sale_last_tx_id' not in session:
                    #     request.session['__website_sale_last_tx_id'] = int(tx.id)   
                    # if 'sale_order_id' not in session:
                    #     request.session['sale_order_id'] = int(tx.sale_order_ids[0].id) 
                    # if 'sale_last_order_id' not in session:
                    #     request.session['sale_last_order_id'] = int(tx.sale_order_ids[0].id) 
                    #--------------------------------------------------------------------------------
                    _logger.info("Updated request.session------------>")
                    _logger.info(request.session)  
            except Exception as e:
                _logger.info(str(e.args))
        return res

    @http.route('/payment/moneris/ipn/', type='http', auth='none', methods=['POST'], csrf=False)
    def moneris_ipn(self, **post):
        """ Moneris IPN. """
        _logger.info("============ipn=================")
        res = self.moneris_validate_data(**post)
        _logger.info("return_url--> " + str(res))
        return werkzeug.utils.redirect('/moneris?{}'.format(res))

    @http.route('/payment/moneris/dpn', type='http', auth="none", methods=['POST'], csrf=False)
    def moneris_dpn(self, **post):
        """ Moneris DPN """
        _logger.info("moneris_dpn-->")
        _logger.info("post--> " + str(post))
        if 'xml_response' in post:
            if 'gift_charge_total' in post['xml_response']:
                if '<receipt_text' in post['xml_response']:
                    part1 = post['xml_response'].split('<receipt_text')[0]
                    part2 = post['xml_response'].split('</receipt_text>')[1]
                    post['xml_response'] = part1+part2
            post = xmltodict.parse(post['xml_response'])
            if 'response' in post:
                post = post['response']
        # {'xml_response': "<?xml version='1.0' standalone='yes'?>\r\n<response>\r\n<response_order_id>S00049-1</response_order_id>\r\n<bank_transaction_id>660144980013442940</bank_transaction_id>\r\n<response_code>027</response_code>\r\n<iso_code>01</iso_code>\r\n<bank_approval_code>699809</bank_approval_code>\r\n<time_stamp>12:47:23</time_stamp>\r\n<date_stamp>2020-09-30</date_stamp>\r\n<trans_name>purchase</trans_name>\r\n<message>APPROVED           *                    =</message>\r\n<charge_total>14.27</charge_total>\r\n<cardholder>TEST CARD</cardholder>\r\n<card_num>4242***4242</card_num>\r\n<card>V</card>\r\n<expiry_date>4912</expiry_date>\r\n<result>1</result>\r\n<txn_num>272196-0_15</txn_num>\r\n<rvaroid>S00049-1</rvaroid>\r\n<rvarret>{&amp;quot;return_url&amp;quot;: &amp;quot;/payment/process&amp;quot;}</rvarret>\r\n<cvd_response_code>M</cvd_response_code>\r\n<transactionKey>DerBayssfXdG380P4hDf44iIhf7Det</transactionKey>\r\n</response>"}
        # OrderedDict([('response', OrderedDict([('response_order_id', 'S00049-1'), ('bank_transaction_id', '660144980013442940'), ('response_code', '027'), ('iso_code', '01'), ('bank_approval_code', '699809'), ('time_stamp', '12:47:23'), ('date_stamp', '2020-09-30'), ('trans_name', 'purchase'), ('message', 'APPROVED           *                    ='), ('charge_total', '14.27'), ('cardholder', 'TEST CARD'), ('card_num', '4242***4242'), ('card', 'V'), ('expiry_date', '4912'), ('result', '1'), ('txn_num', '272196-0_15'), ('rvaroid', 'S00049-1'), ('rvarret', '{&quot;return_url&quot;: &quot;/payment/process&quot;}'), ('cvd_response_code', 'M'), ('transactionKey', 'DerBayssfXdG380P4hDf44iIhf7Det')]))])
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
        _logger.info("Message--> " + str(message))
        return request.render('payment_moneris_hosted.moneris_status', {'status': status, 'transactionKey': transactionKey, 'response_code': response_code, 'message': message})

