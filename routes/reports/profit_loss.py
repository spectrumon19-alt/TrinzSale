from flask import Blueprint, request, jsonify, Response
from db import get_db_connection, release_db_connection
from auth import token_required
from psycopg2.extras import RealDictCursor
from datetime import datetime
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

reports_pl_bp = Blueprint('reports_pl', __name__)

@reports_pl_bp.route('/reports/profit-loss', methods=['GET'])
@token_required
def get_profit_loss_report(payload):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        params = []
        date_filter = ""
        if start_date:
            date_filter += " AND DATE(si.invoice_date) >= %s"
            params.append(start_date)
        if end_date:
            date_filter += " AND DATE(si.invoice_date) <= %s"
            params.append(end_date)

        # Revenue: Total sales
        revenue_query = f"""
            SELECT
                COALESCE(SUM(si.total_amount), 0) as revenue,
                COALESCE(SUM(si.total_gst), 0) as tax_collected
            FROM sales_invoices si
            WHERE si.status = 'Completed' {date_filter}
        """
        cur.execute(revenue_query, params)
        revenue_data = cur.fetchone()
        total_revenue = float(revenue_data['revenue']) if revenue_data['revenue'] else 0.0
        tax_collected = float(revenue_data['tax_collected']) if revenue_data['tax_collected'] else 0.0

        # Cost of Goods Sold: Sum of purchase costs for sold items
        cogs_query = f"""
            SELECT
                COALESCE(SUM(sii.quantity * p.purchase_rate), 0) as cogs
            FROM sales_invoice_items sii
            JOIN products p ON sii.product_id = p.product_id
            JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
            WHERE si.status = 'Completed' {date_filter}
        """
        cur.execute(cogs_query, params)
        cogs_data = cur.fetchone()
        cost_of_goods_sold = float(cogs_data['cogs']) if cogs_data['cogs'] else 0.0

        # Gross Profit
        gross_profit = total_revenue - cost_of_goods_sold
        gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

        # Operating Expenses (approximated from returns/discounts)
        expenses_query = f"""
            SELECT
                COALESCE(SUM(si.discount_amount), 0) as discounts,
                COALESCE(SUM(sr.total_amount), 0) as returns
            FROM sales_invoices si
            LEFT JOIN sales_returns sr ON si.invoice_id = sr.original_invoice_id
            WHERE si.status = 'Completed' {date_filter}
        """
        cur.execute(expenses_query, params)
        expenses_data = cur.fetchone()
        discounts = float(expenses_data['discounts']) if expenses_data['discounts'] else 0.0
        returns = float(expenses_data['returns']) if expenses_data['returns'] else 0.0
        total_expenses = discounts + returns

        # Net Profit
        net_profit = gross_profit - total_expenses
        net_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0

        # Daily breakdown
        daily_query = f"""
            SELECT
                DATE(si.invoice_date) as report_date,
                COALESCE(SUM(si.total_amount), 0) as daily_revenue,
                COALESCE(SUM(sii.quantity * p.purchase_rate), 0) as daily_cogs,
                COALESCE(SUM(si.discount_amount), 0) as daily_discounts
            FROM sales_invoices si
            LEFT JOIN sales_invoice_items sii ON si.invoice_id = sii.invoice_id
            LEFT JOIN products p ON sii.product_id = p.product_id
            WHERE si.status = 'Completed' {date_filter}
            GROUP BY DATE(si.invoice_date)
            ORDER BY report_date DESC
        """
        cur.execute(daily_query, params)
        daily_breakdown = cur.fetchall()

        # Process daily breakdown
        daily_data = []
        for row in daily_breakdown:
            daily_revenue = float(row['daily_revenue']) if row['daily_revenue'] else 0.0
            daily_cogs = float(row['daily_cogs']) if row['daily_cogs'] else 0.0
            daily_discounts = float(row['daily_discounts']) if row['daily_discounts'] else 0.0
            daily_gross_profit = daily_revenue - daily_cogs
            daily_net_profit = daily_gross_profit - daily_discounts

            daily_data.append({
                'date': str(row['report_date']),
                'revenue': round(daily_revenue, 2),
                'cogs': round(daily_cogs, 2),
                'gross_profit': round(daily_gross_profit, 2),
                'expenses': round(daily_discounts, 2),
                'net_profit': round(daily_net_profit, 2),
                'margin': round((daily_net_profit / daily_revenue * 100) if daily_revenue > 0 else 0, 2)
            })

        return jsonify({
            'summary': {
                'revenue': round(total_revenue, 2),
                'tax_collected': round(tax_collected, 2),
                'cogs': round(cost_of_goods_sold, 2),
                'gross_profit': round(gross_profit, 2),
                'gross_margin': round(gross_margin, 2),
                'expenses': round(total_expenses, 2),
                'net_profit': round(net_profit, 2),
                'net_margin': round(net_margin, 2),
            },
            'breakdown': {
                'discounts': round(discounts, 2),
                'returns': round(returns, 2),
            },
            'daily': daily_data
        })

    except Exception as e:
        print(f"Error generating P&L report: {str(e)}")
        return jsonify({'message': 'Failed to generate report', 'error': str(e)}), 500
    finally:
        cur.close()
        release_db_connection(conn)


@reports_pl_bp.route('/reports/profit-loss/export', methods=['GET'])
@token_required
def export_profit_loss_report(payload):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        params = []
        date_filter = ""
        if start_date:
            date_filter += " AND DATE(si.invoice_date) >= %s"
            params.append(start_date)
        if end_date:
            date_filter += " AND DATE(si.invoice_date) <= %s"
            params.append(end_date)

        # Revenue
        revenue_query = f"""
            SELECT
                COALESCE(SUM(si.total_amount), 0) as revenue,
                COALESCE(SUM(si.total_gst), 0) as tax_collected
            FROM sales_invoices si
            WHERE si.status = 'Completed' {date_filter}
        """
        cur.execute(revenue_query, params)
        revenue_data = cur.fetchone()
        total_revenue = float(revenue_data['revenue']) if revenue_data['revenue'] else 0.0
        tax_collected = float(revenue_data['tax_collected']) if revenue_data['tax_collected'] else 0.0

        # COGS
        cogs_query = f"""
            SELECT
                COALESCE(SUM(sii.quantity * p.purchase_rate), 0) as cogs
            FROM sales_invoice_items sii
            JOIN products p ON sii.product_id = p.product_id
            JOIN sales_invoices si ON sii.invoice_id = si.invoice_id
            WHERE si.status = 'Completed' {date_filter}
        """
        cur.execute(cogs_query, params)
        cogs_data = cur.fetchone()
        cost_of_goods_sold = float(cogs_data['cogs']) if cogs_data['cogs'] else 0.0

        # Gross Profit
        gross_profit = total_revenue - cost_of_goods_sold
        gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0

        # Expenses
        expenses_query = f"""
            SELECT
                COALESCE(SUM(si.discount_amount), 0) as discounts,
                COALESCE(SUM(sr.total_amount), 0) as returns
            FROM sales_invoices si
            LEFT JOIN sales_returns sr ON si.invoice_id = sr.original_invoice_id
            WHERE si.status = 'Completed' {date_filter}
        """
        cur.execute(expenses_query, params)
        expenses_data = cur.fetchone()
        discounts = float(expenses_data['discounts']) if expenses_data['discounts'] else 0.0
        returns = float(expenses_data['returns']) if expenses_data['returns'] else 0.0
        total_expenses = discounts + returns

        # Net Profit
        net_profit = gross_profit - total_expenses
        net_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0

        # Daily breakdown with detailed metrics
        daily_query = f"""
            SELECT
                DATE(si.invoice_date) as report_date,
                COUNT(DISTINCT si.invoice_id) as invoice_count,
                COALESCE(SUM(si.total_amount), 0) as daily_revenue,
                COALESCE(SUM(si.total_gst), 0) as daily_gst,
                COALESCE(SUM(sii.quantity * p.purchase_rate), 0) as daily_cogs,
                COALESCE(SUM(si.discount_amount), 0) as daily_discounts,
                COALESCE(SUM(sr.total_amount), 0) as daily_returns
            FROM sales_invoices si
            LEFT JOIN sales_invoice_items sii ON si.invoice_id = sii.invoice_id
            LEFT JOIN products p ON sii.product_id = p.product_id
            LEFT JOIN sales_returns sr ON si.invoice_id = sr.original_invoice_id
            WHERE si.status = 'Completed' {date_filter}
            GROUP BY DATE(si.invoice_date)
            ORDER BY report_date DESC
        """
        cur.execute(daily_query, params)
        daily_breakdown = cur.fetchall()

        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "P&L Report"

        # Define styles
        header_font = Font(bold=True, size=12, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
        summary_font = Font(bold=True, size=11)
        summary_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        total_fill = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")
        total_font = Font(bold=True, color="FFFFFF")
        currency_format = '₹#,##0.00'
        percent_format = '0.00"%"'
        center_alignment = Alignment(horizontal='center', vertical='center')

        # Title
        ws['A1'] = "PROFIT & LOSS STATEMENT"
        ws['A1'].font = Font(bold=True, size=14)
        ws.merge_cells('A1:D1')

        # Date range
        ws['A2'] = f"Period: {start_date} to {end_date}"
        ws.merge_cells('A2:D2')

        # P&L Statement
        ws['A4'] = "P&L STATEMENT"
        ws['A4'].font = header_font
        ws['A4'].fill = header_fill
        ws.merge_cells('A4:D4')

        row = 5
        # Revenue
        ws[f'A{row}'] = "REVENUE"
        ws[f'B{row}'] = total_revenue
        ws[f'B{row}'].number_format = currency_format
        ws[f'A{row}'].font = summary_font
        row += 1

        ws[f'A{row}'] = "Tax Collected (GST)"
        ws[f'B{row}'] = tax_collected
        ws[f'B{row}'].number_format = currency_format
        row += 1

        # COGS
        ws[f'A{row}'] = "COST OF GOODS SOLD"
        ws[f'B{row}'] = cost_of_goods_sold
        ws[f'B{row}'].number_format = currency_format
        ws[f'A{row}'].font = summary_font
        ws[f'A{row}'].fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
        row += 1

        # Gross Profit
        ws[f'A{row}'] = "GROSS PROFIT"
        ws[f'B{row}'] = gross_profit
        ws[f'B{row}'].number_format = currency_format
        ws[f'C{row}'] = gross_margin
        ws[f'C{row}'].number_format = percent_format
        ws[f'A{row}'].font = summary_font
        ws[f'A{row}'].fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
        row += 1

        # Expenses breakdown
        ws[f'A{row}'] = "OPERATING EXPENSES"
        ws[f'A{row}'].font = summary_font
        row += 1

        ws[f'A{row}'] = "  Discounts Given"
        ws[f'B{row}'] = discounts
        ws[f'B{row}'].number_format = currency_format
        row += 1

        ws[f'A{row}'] = "  Returns & Refunds"
        ws[f'B{row}'] = returns
        ws[f'B{row}'].number_format = currency_format
        row += 1

        # Net Profit
        row += 1
        ws[f'A{row}'] = "NET PROFIT"
        ws[f'B{row}'] = net_profit
        ws[f'B{row}'].number_format = currency_format
        ws[f'C{row}'] = net_margin
        ws[f'C{row}'].number_format = percent_format
        ws[f'A{row}'].font = total_font
        ws[f'A{row}'].fill = total_fill
        ws[f'B{row}'].font = total_font
        ws[f'B{row}'].fill = total_fill
        ws[f'C{row}'].font = total_font
        ws[f'C{row}'].fill = total_fill

        # Daily Breakdown Sheet
        if daily_breakdown:
            ws2 = wb.create_sheet("Daily Breakdown")
            ws2['A1'] = "DAILY PROFIT & LOSS BREAKDOWN"
            ws2['A1'].font = Font(bold=True, size=12)
            ws2.merge_cells('A1:L1')

            # Headers
            headers = ['Date', 'Invoices', 'Revenue', 'GST', 'COGS', 'Gross Profit', 'Gross %', 'Discounts', 'Returns', 'Expenses', 'Net Profit', 'Net %']
            ws2.append(headers)
            for col_num, header in enumerate(headers, 1):
                cell = ws2.cell(row=2, column=col_num)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center_alignment

            # Daily data
            row_num = 3
            for row_data in daily_breakdown:
                daily_revenue = float(row_data['daily_revenue']) if row_data['daily_revenue'] else 0.0
                daily_gst = float(row_data['daily_gst']) if row_data['daily_gst'] else 0.0
                daily_cogs = float(row_data['daily_cogs']) if row_data['daily_cogs'] else 0.0
                daily_discounts = float(row_data['daily_discounts']) if row_data['daily_discounts'] else 0.0
                daily_returns = float(row_data['daily_returns']) if row_data['daily_returns'] else 0.0
                daily_gross_profit = daily_revenue - daily_cogs
                daily_gross_margin = (daily_gross_profit / daily_revenue * 100) if daily_revenue > 0 else 0
                daily_expenses = daily_discounts + daily_returns
                daily_net_profit = daily_gross_profit - daily_expenses
                daily_net_margin = (daily_net_profit / daily_revenue * 100) if daily_revenue > 0 else 0
                invoice_count = int(row_data['invoice_count']) if row_data['invoice_count'] else 0

                ws2[f'A{row_num}'] = str(row_data['report_date'])
                ws2[f'B{row_num}'] = invoice_count
                ws2[f'C{row_num}'] = daily_revenue
                ws2[f'D{row_num}'] = daily_gst
                ws2[f'E{row_num}'] = daily_cogs
                ws2[f'F{row_num}'] = daily_gross_profit
                ws2[f'G{row_num}'] = daily_gross_margin
                ws2[f'H{row_num}'] = daily_discounts
                ws2[f'I{row_num}'] = daily_returns
                ws2[f'J{row_num}'] = daily_expenses
                ws2[f'K{row_num}'] = daily_net_profit
                ws2[f'L{row_num}'] = daily_net_margin

                # Format columns
                ws2[f'B{row_num}'].number_format = '0'
                for col in ['C', 'D', 'E', 'F', 'H', 'I', 'J', 'K']:
                    ws2[f'{col}{row_num}'].number_format = currency_format
                for col in ['G', 'L']:
                    ws2[f'{col}{row_num}'].number_format = percent_format

                # Highlight net profit
                if daily_net_profit >= 0:
                    ws2[f'K{row_num}'].fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
                else:
                    ws2[f'K{row_num}'].fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

                row_num += 1

            # Auto-adjust column widths
            col_widths = {'A': 12, 'B': 10, 'C': 14, 'D': 12, 'E': 14, 'F': 14, 'G': 10, 'H': 12, 'I': 12, 'J': 12, 'K': 14, 'L': 10}
            for col, width in col_widths.items():
                ws2.column_dimensions[col].width = width

        # Auto-adjust column widths for main sheet
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 15

        # Generate file
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        filename = f"profit_loss_{start_date}_to_{end_date}.xlsx"
        response = Response(
            output.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

        return response

    except Exception as e:
        print(f"Error exporting P&L report: {str(e)}")
        return jsonify({'message': 'Failed to export P&L report', 'error': str(e)}), 500
    finally:
        cur.close()
