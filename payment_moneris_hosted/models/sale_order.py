# -*- coding: utf-'8' "-*-"

from odoo import api, fields, models

class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'

    def has_to_be_paid(self, also_in_draft=False):
        transaction = self.get_portal_last_transaction()
        if self.company_id.portal_pay_afterconfirm and self.company_id.portal_confirmation_pay and self.require_payment == True:
            return (self.state == 'sent' or (self.state == 'draft' and also_in_draft) or self.state == 'sale') and not self.is_expired and self.require_payment and transaction.state != 'done' and self.amount_total            
        return (self.state == 'sent' or (self.state == 'draft' and also_in_draft)) and not self.is_expired and self.require_payment and transaction.state != 'done' and self.amount_total

