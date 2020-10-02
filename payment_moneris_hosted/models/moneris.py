# -*- coding: utf-'8' "-*-"

import base64

import logging
from urllib.parse import urljoin
import werkzeug
from werkzeug import urls
import urllib.request
import json

from odoo import api, fields, models, _
from odoo.addons.payment.models.payment_acquirer import ValidationError
from odoo.addons.payment_moneris_hosted.controllers.main import MonerisController
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class AcquirerMoneris(models.Model):
    _inherit = 'payment.acquirer'

    provider = fields.Selection(selection_add=[('moneris', 'Moneris')])
    moneris_transaction_type = fields.Selection(string='Transaction Type', selection=[('preauthorization', 'Preauthorization'), ('purchase', 'Purchase')], default = 'purchase')
    moneris_psstore_id = fields.Char(string='Moneris PS Store ID')
    moneris_hpp_key = fields.Char(string='Moneris HPP Key')
    moneris_use_ipn = fields.Boolean('Use IPN', default=True, help='Moneris Instant Payment Notification')
    # Server 2 server
    # moneris_store_id = fields.Char(string='Store ID', help='Store Id in Moneris Direct Host Configuration')
    # moneris_api_token = fields.Char(string='Api Token', help='Api Token in Moneris Direct Host Configuration')
    # moneris_api_enabled = fields.Boolean('Moneris Api Enable', default=True)

    moneris_image_url = fields.Char("Checkout Image URL", groups='base.group_user', help="A relative absolute URL pointing to a square image of your "
        "brand or product. As defined in your moneris_onsite profile. See: https://moneris_onsite.com/docs/checkout")
    moneris_order_confirmation = fields.Selection(string='Order Confirmation', selection=[
        # ('none', 'No Automatic Confirmation'),
        # ('authorize', 'Authorize the amount and confirm it'),
        ('capture','Authorize & capture the amount and conform it')], default='capture', readonly=True)
    moneris_store_card = fields.Selection(string='Store Card Data', selection=[
        ('never', 'Never'), 
        ('customer', 'Let the customer decide'),
        ('always','Always')], default='never')
    # moneris_payment_flow = fields.Selection(string='Moneris Payment Flow', selection=[  ('redirect', 'Redirection to the acuirer website'), 
    # ('odoo', 'Payment from Odoo')], default='redirect')         

    fees_active = fields.Boolean(default=False)
    fees_dom_fixed = fields.Float(default=0.35)
    fees_dom_var = fields.Float(default=3.4)
    fees_int_fixed = fields.Float(default=0.35)
    fees_int_var = fields.Float(default=3.9)

    def _get_moneris_urls(self, environment):
        _logger.info("_get_moneris_urls")
        _logger.info(str(self) + "," +  str(environment))
        """ Moneris URLS """
        if environment == 'enabled':
            moneris_url =  {
                'moneris_form_url': 'https://www3.moneris.com/HPPDP/index.php',
                'moneris_auth_url': 'https://www3.moneris.com/HPPDP/verifyTxn.php',
            }
        else:
            moneris_url =  {
                'moneris_form_url': 'https://esqa.moneris.com/HPPDP/index.php',
                'moneris_auth_url': 'https://esqa.moneris.com/HPPDP/verifyTxn.php',
            }

        _logger.info(moneris_url)
        return moneris_url

    def moneris_compute_fees(self, amount, currency_id, country_id):
        _logger.info("moneris_compute_fees-->")
        if not self.fees_active:
            return 0.0
        country = self.env['res.country'].browse(country_id)
        if country and self.company_id.country_id.id == country.id:
            percentage = self.fees_dom_var
            fixed = self.fees_dom_fixed
        else:
            percentage = self.fees_int_var
            fixed = self.fees_int_fixed
        fees = (percentage / 100.0 * amount + fixed) / (1 - percentage / 100.0)
        _logger.info(str(fees))
        return fees

    def moneris_form_generate_values(self, values):
        _logger.info("moneris_form_generate_values-->")
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        moneris_tx_values = dict(values)
        moneris_tx_values.update({
            'cmd': '_xclick',
            'business': self.moneris_psstore_id,
            'item_name': '%s: %s' % (self.company_id.name, values['reference']),
            'item_number': values['reference'],
            'amount': values['amount'],
            'currency_code': values['currency'] and values['currency'].name or '',
            'address1': values.get('partner_address'),
            'city': values.get('partner_city'),
            'country': values.get('partner_country') and values.get('partner_country').code or '',
            'state': values.get('partner_state') and (
                        values.get('partner_state').code or values.get('partner_state').name) or '',
            'email': values.get('partner_email') or '',
            'zip_code': values.get('partner_zip') or '',
            'first_name': values.get('partner_first_name') or '',
            'last_name': values.get('partner_last_name') or '',
            'moneris_return': urls.url_join(base_url, MonerisController._return_url),
            'notify_url': urls.url_join(base_url, MonerisController._notify_url),
            'cancel_return': urls.url_join(base_url, MonerisController._cancel_url),
            'handling': '%.2f' % moneris_tx_values.pop('fees', 0.0) if self.fees_active else False,
            'custom': json.dumps({'return_url': '%s' % moneris_tx_values.pop('return_url')}) if moneris_tx_values.get(
                'return_url') else False,
        })

        # Display Items
        order_lines = []
        order_name = values['reference'].split("-")[0] if len(values['reference'].split("-")) > 1 else values['reference']
        order_id = self.env['sale.order'].sudo().search([('name','=',order_name)])
        i =1
        shipping_cost = 0.0 
        gst = pst = hst = 0
        for line in order_id.order_line:
            item ={}
            item['name'] = str(i)
            item['id'] = line.product_id.default_code or line.product_id.id#Product Code - SKU (max 10 chars)
            item['description'] = line.product_id.name[:15]#Product Description - (max 15chars)
            item['quantity'] = line.product_uom_qty#Quantity of Goods Purchased -(max - 4 digits)
            item['price'] = line.price_unit#Unit Price - (max - "7"."2" digits,i.e. min 0.00 & max 9999999.99)
            item['subtotal'] = line.price_subtotal#Quantity X Price of Product -(max - "7"."2" digits, i.e. min0.00 & max 9999999.99)
            order_lines.append(item)
            i += 1
            if line.tax_id:
                if 'gst' in line.tax_id.name.lower():
                    gst += line.price_tax
                if 'pst' in line.tax_id.name.lower():
                    pst += line.price_tax
                if 'hst' in line.tax_id.name.lower():
                    hst += line.price_tax
        moneris_tx_values['order_lines'] = order_lines
        moneris_tx_values['cust_id'] = values.get('partner_id')
        # Computes taxes and Shipping Cost
        moneris_tx_values['gst'] = gst
        moneris_tx_values['pst'] = pst
        moneris_tx_values['hst'] = hst
        moneris_tx_values['shipping_cost'] = 0.0
        moneris_tx_values['note'] = ''
        moneris_tx_values['email'] = values.get('billing_partner_email')
        return moneris_tx_values

    def moneris_get_form_action_url(self):
        self.ensure_one()
        _logger.info("moneris_get_form_action_url--->")
        _logger.info("State-->" + str(self.state))
        # environment = 'prod' if self.state == 'enabled' else 'test'
        # _logger.info(environment)
        moneris_form_url = self._get_moneris_urls(self.state)['moneris_form_url']
        _logger.info("moneris_form_url-------->")
        _logger.info(moneris_form_url)
        return moneris_form_url


class TxMoneris(models.Model):
    _inherit = 'payment.transaction'

    moneris_txn_type = fields.Char('Transaction type')
    moneris_customer_id = fields.Char('Customer Id')
    moneris_receipt_id = fields.Char('Receipt Id')
    moneris_response_code = fields.Char('Response Code')
    moneris_credit_card = fields.Char('Credit Card')
    moneris_expiry_date = fields.Char('Expiry Date')
    moneris_transaction_time = fields.Char('Transaction Time')
    moneris_transaction_date = fields.Char('Transaction Date')
    moneris_transaction_id = fields.Char('Transaction ID')
    moneris_payment_type = fields.Char('Payment Type')
    moneris_reference_no = fields.Char('Reference Number')
    moneris_txn_type = fields.Char('Transaction Type')
    
    moneris_bank_approval = fields.Char('Bank Approval')
    moneris_card_holder = fields.Char('Cardholder')
    moneris_order_id = fields.Char('Response Order Id')
    moneris_iso_code = fields.Char('Iso Code')
    moneris_transaction_key = fields.Char('Transaction Key')
    moneris_transaction_no = fields.Char('Transaction Number')

    # --------------------------------------------------
    # FORM RELATED METHODS
    # --------------------------------------------------

    @api.model
    def _moneris_form_get_tx_from_data(self, data):
        _logger.info("_moneris_form_get_tx_from_data-->")
        _logger.info(data)
        reference, txn_id = data.get('rvaroid'), data.get('txn_num')
        if not reference or not txn_id:
            error_msg = _('Moneris: received data with missing reference (%s) or txn_id (%s)') % (reference, txn_id)
            _logger.info(error_msg)
            raise ValidationError(error_msg)

        # find tx -> @TDENOTE use txn_id ?
        txs = self.env['payment.transaction'].search([('reference', '=', reference)])
        if not txs or len(txs) > 1:
            error_msg = 'Moneris: received data for reference %s' % (reference)
            if not txs:
                error_msg += '; no order found'
            else:
                error_msg += '; multiple order found'
            _logger.info(error_msg)
            raise ValidationError(error_msg)
        _logger.info(txs[0])
        return txs[0]

    def _moneris_form_get_invalid_parameters(self,  data):
        invalid_parameters = []
        """
        if data.get('notify_version')[0] != '3.4':
            _logger.warning(
                'Received a notification from Moneris with version %s instead of 2.6. This could lead to issues when managing it.' %
                data.get('notify_version')
            )
        if data.get('test_ipn'):
            _logger.warning(
                'Received a notification from Moneris using sandbox'
            ),
        """
        # TODO: txn_id: shoudl be false at draft, set afterwards, and verified with txn details
        if self.acquirer_reference and data.get('response_order_id') != self.acquirer_reference:
            invalid_parameters.append(('response_order_id', data.get('response_order_id'), self.acquirer_reference))
        # check what is buyed
        if float_compare(float(data.get('charge_total', '0.0')), (self.amount), 2) != 0:
            invalid_parameters.append(('charge_total', data.get('charge_total'), '%.2f' % self.amount))
        """
        if data.get('mc_currency') != tx.currency_id.name:
            invalid_parameters.append(('mc_currency', data.get('mc_currency'), tx.currency_id.name))
        """
        """
        if 'handling_amount' in data and float_compare(float(data.get('handling_amount')), tx.fees, 2) != 0:
            invalid_parameters.append(('handling_amount', data.get('handling_amount'), tx.fees))
        """
        # check buyer
        """
        if tx.partner_reference and data.get('payer_id') != tx.partner_reference:
            invalid_parameters.append(('payer_id', data.get('payer_id'), tx.partner_reference))
        """
        # check seller
        '''
        if data.get('rvarid') != tx.acquirer_id.moneris_psstore_id:
            invalid_parameters.append(('rvarid', data.get('rvarid'), tx.acquirer_id.moneris_psstore_id))
        if data.get('rvarkey') != tx.acquirer_id.moneris_seller_account:
            invalid_parameters.append(('rvarkey', data.get('rvarkey'), tx.acquirer_id.moneris_seller_account))
        '''
        return invalid_parameters

    def _moneris_form_validate(self, data):
        _logger.info(data)
        status = data.get('result')
        _logger.info("-----------------form -----validate----------------------")
        if status == '1':
            _logger.info('Validated Moneris payment for tx %s: set as done' % (self.reference))
            data.update(state='done', date_validate=data.get('date_stamp', fields.datetime.now()))
            _logger.info("---form validate----------------------")
            tranrec = self._moneris_convert_transaction(data)
            _logger.info(tranrec)
            response = self.sudo().write(tranrec)
            _logger.info(response)
            return response
        else:
            error = 'Received unrecognized status for Moneris payment %s: %s, set as error' % (self.reference, status)
            _logger.info(error)
            data.update(state='error', state_message=error)
            response = self.sudo().write(data)
            return response
        _logger.info("_moneris_form_validate-->" + str(response))

    def _moneris_convert_transaction(self, data):
        _logger.info("_moneris_convert_transaction")
        _logger.info(str(data))
        try:
            transaction = {}
            transaction['acquirer_reference'] = data['bank_transaction_id']
            transaction['amount'] = data['charge_total']
            transaction['date'] = data['date_validate']
            # transaction['fees'] = 0.0#Set by Back-end#Fees#Monetary
            transaction['partner_country_id'] = int(data['iso_code'])#Country#Many2one#     Required
            # transaction['payment_token_id'] = ""#Payment Token#Many2one
            # transaction['reference'] = ""#Reference#Char#Required#Automatic
            transaction['state'] = data['state']
            transaction['state_message'] = data['message'].replace("\n","")
            transaction['type'] = "validation"
            # Moneris Details
            transaction['moneris_customer_id'] = data['moneris_customer_id'] if 'moneris_customer_id' in data else ''
            transaction['moneris_receipt_id'] = data['rvaroid'] if 'rvaroid' in data else ''
            transaction['moneris_response_code'] = data['response_code'] if 'response_code' in data else ''
            transaction['moneris_credit_card'] = data['f4l4'] if 'f4l4' in data else ''
            transaction['moneris_expiry_date'] = data['expiry_date'] if 'expiry_date' in data else ''
            transaction['moneris_transaction_time'] = data['time_stamp'] if 'time_stamp' in data else ''
            transaction['moneris_transaction_date'] = data['date_validate'] if 'date_validate' in data else ''
            transaction['moneris_transaction_id'] = data['txn_num'] if 'txn_num' in data else ''
            transaction['moneris_payment_type'] = data['trans_name'] if 'trans_name' in data else ''
            transaction['moneris_reference_no'] = data['moneris_reference_no'] if 'moneris_reference_no' in data else ''
            transaction['moneris_txn_type'] = data['trans_name'] if 'trans_name' in data else ''
            transaction['moneris_bank_approval'] = data['bank_approval_code'] if 'bank_approval_code' in data else ''
            transaction['moneris_card_holder'] = data['cvd_response_code'] if 'cvd_response_code' in data else ''
            transaction['moneris_order_id'] = data['rvaroid'] if 'rvaroid' in data else ''
            transaction['moneris_iso_code'] = data['iso_code'] if 'iso_code' in data else ''
            transaction['moneris_transaction_key'] = data['transactionKey'] if 'transactionKey' in data else ''
            transaction['moneris_transaction_no'] = data['txn_num'] if 'txn_num' in data else ''
            # Payment Token is not saved
            _logger.info(str("Transaction"))
            _logger.info(str(transaction))
            return transaction
        except Exception as e:
            return {'error':str(e.args)}

    # # --------------------------------------------------
    # # SERVER2SERVER RELATED METHODS
    # # --------------------------------------------------

    # def _moneris_try_url(self, request, tries=3, context=None):
    #     """ Try to contact Moneris. Due to some issues, internal service errors
    #     seem to be quite frequent. Several tries are done before considering
    #     the communication as failed.
    #      .. versionadded:: pre-v8 saas-3
    #      .. warning::
    #         Experimental code. You should not use it before OpenERP v8 official
    #         release.
    #     """
    #     done, res = False, None
    #     while (not done and tries):
    #         try:
    #             res = urllib.request.urlopen(request)
    #             done = True
    #         except urllib.request.HTTPError as e:
    #             res = e.read()
    #             e.close()
    #             if tries and res and json.loads(res)['name'] == 'INTERNAL_SERVICE_ERROR':
    #                 _logger.warning('Failed contacting Moneris, retrying (%s remaining)' % tries)
    #         tries = tries - 1
    #     if not res:
    #         pass
    #         # raise openerp.exceptions.
    #     result = res.read()
    #     res.close()
    #     return result