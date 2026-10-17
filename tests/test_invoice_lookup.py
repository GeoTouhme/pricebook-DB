from decimal import Decimal
import unittest
import pandas as pd
from invoice_lookup import prepare_history, find_items, item_history, purchase_summary, history_export
from dashboard_data import load_data, ROOT
from auth_helpers import logged_in_app


class InvoiceLookupTests(unittest.TestCase):
    def setUp(self):
        self.products=pd.DataFrame([
            dict(upc='033544000250',name='Corona Familiar Can',size='24 OZ'),
            dict(upc='033544950531',name='Corona Familiar Bottles',size='12 PK 12 OZ'),
            dict(upc='071990095062',name='BLUEMOON CANS 12 OZ',size='12 PK 12 OZ')])
        self.invoices=pd.DataFrame([
            dict(id=1,invoice_date=pd.Timestamp('2026-01-01'),invoice_number='A',supplier='One',supplier_id=1),
            dict(id=2,invoice_date=pd.Timestamp('2026-02-01'),invoice_number='B',supplier='One',supplier_id=1),
            dict(id=3,invoice_date=pd.Timestamp('2026-03-01'),invoice_number='C',supplier='Two',supplier_id=2)])
        def line(id,invoice_id,**kw):
            return dict(id=id,invoice_id=invoice_id,line_number=id,product_number='48367',
                pack_upc='00033544000250',source_upc='00033544000243',matched_upc='033544000250',
                description='CORONA FAMILAR C12 24OZ',quantity='1',unit_of_measure='CA',ppc='12',
                unit_cost='30.15',discount_cents=0,adjustments_cents=120,extended_price='31.35',**kw)
        first=line(1,1); credit=line(2,3);credit.update(quantity='-1',extended_price='-31.35',adjustments_cents=-120)
        bottle=line(3,2);bottle.update(pack_upc='00033544950531',matched_upc='033544950531',description='Corona Familiar bottles')
        unknown=line(4,2);unknown.update(pack_upc='070655001929',matched_upc=None,description='Supplier only item',product_number='U1')
        no_code=line(5,2);no_code.update(pack_upc='',matched_upc=None,product_number='',description='Code missing alpha')
        other=line(6,2);other.update(pack_upc='',matched_upc=None,product_number='',description='Code missing beta')
        self.lines=pd.DataFrame([first,credit,bottle,unknown,no_code,other])
        self.history=prepare_history(self.lines,self.invoices)

    def test_upc_padding_sku_and_no_case_upc_substitution(self):
        for query in ['033544000250','00033544000250','="00033544000250"']:
            items=find_items(query,self.products,self.history)
            self.assertEqual([item['upc'] for item in items],['033544000250'])
        self.assertEqual(find_items('00033544000243',self.products,self.history),[])
        # A supplier code can describe more than one source pack: show choices.
        self.assertGreater(len(find_items('48367',self.products,self.history)),1)
        self.assertEqual(find_items('3.3544E+09',self.products,self.history),[])

    def test_name_search_separates_pack_variants_and_handles_punctuation(self):
        found=find_items('Corona Familiar',self.products,self.history)
        self.assertEqual({item['upc'] for item in found},{'033544000250','033544950531'})
        self.assertEqual([item['upc'] for item in find_items('Blue Moon 12pk',self.products,self.history)],['071990095062'])
        self.assertEqual(find_items('[',self.products,self.history),[])
        self.assertEqual(find_items('',self.products,self.history),[])

    def test_unlinked_source_items_and_blank_identifiers_stay_separate(self):
        item=find_items('U1',self.products,self.history)[0]
        self.assertFalse(item['catalog'])
        self.assertEqual(item['upc'],'070655001929')
        items=find_items('Code missing',self.products,self.history)
        self.assertEqual(len(items),2)
        self.assertNotEqual(items[0]['key'],items[1]['key'])
        variants=self.lines.iloc[4:].copy()
        variants['product_number']='SHARED'
        variants['ppc']=['6','12']
        choices=find_items('SHARED',self.products,prepare_history(variants,self.invoices))
        self.assertEqual(len(choices),2)

    def test_confirmed_mapping_takes_precedence_over_conflicting_pack_upc(self):
        lines=self.lines.copy();lines.loc[0,'pack_upc']='00071990095062'
        history=prepare_history(lines,self.invoices)
        blue=find_items('071990095062',self.products,history)[0]
        self.assertTrue(item_history(history,blue['key']).empty)
        self.assertEqual(len(item_history(history,'upc:033544000250')),2)

    def test_credits_exact_totals_and_latest_positive_purchase(self):
        history=item_history(self.history,'upc:033544000250')
        summary=purchase_summary(history)
        self.assertEqual(summary['net_total'],Decimal('0.00'))
        self.assertEqual(summary['credit_lines'],1)
        self.assertEqual(summary['invoice_count'],2)
        self.assertEqual(summary['latest']['invoice_number'],'A')
        self.assertEqual(history_export(history)['Original PACK UPC'].iloc[0],'00033544000250')
        self.assertEqual(history_export(history)['Invoice quantity'].iloc[0],'-1')
        self.assertNotIn('CASE UPC',history_export(history).columns)

    def test_original_user_products_and_history_are_read_only(self):
        data=load_data();history=prepare_history(data['purchase_lines'],data['invoices'])
        corona=find_items('033544000250',data['products'],history)[0]
        summary=purchase_summary(item_history(history,corona['key']))
        self.assertEqual(summary['net_total'],Decimal('250.80'))
        self.assertEqual(summary['latest']['invoice_number'],'100981704')
        blue=find_items('071990095062',data['products'],history)[0]
        self.assertTrue(blue['catalog'])
        self.assertTrue(item_history(history,blue['key']).empty)

    def test_dashboard_lookup_catalog_only_history_filters_and_mobile_navigation(self):
        app=logged_in_app(str(ROOT/'dashboard.py'),default_timeout=30)
        app.selectbox(key='mobile_page').set_value('Invoice lookup').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key='navigation').value,'Invoice lookup')
        app.text_input(key='invoice_lookup_query').set_value('071990095062').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[1].value,'$33.30 / 2 unit(s)')
        self.assertTrue(any('16.65' in c.value for c in app.caption))
        self.assertTrue(any('No matching invoice lines' in i.value for i in app.info))
        app.text_input(key='invoice_lookup_query').set_value('033544000250').run()
        self.assertFalse(app.exception)
        self.assertTrue(any(m.label=='Net line total' and m.value=='$250.80' for m in app.metric))
        self.assertEqual(len(app.dataframe[0].value),10)
        self.assertTrue(any('100981704' in m.value for m in app.markdown))
        # Pick an unreported date: distinguish filtered-out history from none imported.
        app.date_input[0].set_value((pd.Timestamp('2026-06-01').date(),pd.Timestamp('2026-06-02').date())).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('No invoices match this period' in i.value for i in app.info))
        app.text_input(key='invoice_lookup_query').set_value('Corona Familiar').run()
        self.assertFalse(app.exception)
        self.assertGreater(len(next(s for s in app.selectbox if s.label=='Matching product').options),1)
        app.text_input(key='invoice_lookup_query').set_value('no-such-product-xyz').run()
        self.assertTrue(any('No matching product or invoice item' in i.value for i in app.info))
