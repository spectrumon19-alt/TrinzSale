# Point of Sale (POS) System

A complete web-based Point of Sale system with Python backend, PostgreSQL database, and HTML/CSS/JavaScript frontend.

## Features

- **User Authentication**: Secure login with JWT tokens
- **Sales Management**: Process sales transactions with GST calculations
- **Purchase Management**: Record incoming stock from suppliers
- **Inventory Management**: Track stock levels and receive new stock
- **Product Management**: Add, edit, and delete products
- **User Management**: Create and manage users with different roles
- **Reporting**: Generate sales reports with charts
- **Invoice Cancellation**: Admins can cancel invoices and restore stock
- **Printable Receipts**: Generate printable receipts for customers
- **Bulk Data Upload**: Upload products, sales, and purchase data from Excel files
- **Executable Distribution**: Run as a standalone Windows application
- **Mobile Responsive Design**: Fully optimized for mobile and tablet devices

## Technology Stack

- **Backend**: Python with Flask
- **Database**: PostgreSQL
- **Frontend**: HTML5, CSS3, JavaScript (no frameworks)
- **Authentication**: JWT tokens
- **Password Security**: passlib for password hashing
- **Charts**: Chart.js for reporting
- **Excel Processing**: openpyxl for Excel file handling

## Setup Instructions

### Prerequisites

1. Python 3.7 or higher
2. PostgreSQL database
3. Node.js and npm (for any frontend build tools if needed)

### Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd pos-system
   ```

2. Create a virtual environment:
   ```
   # On Windows
   python -m venv venv
   venv\Scripts\activate
   
   # On macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up the PostgreSQL database:
   - Create a new database in PostgreSQL
   - Update the database connection details in the `.env` file
   - Run the schema.sql script to create tables:
     ```
     psql -U <username> -d <database_name> -f schema.sql
     ```

5. Create a `.env` file with the following variables:
   ```
   SECRET_KEY=your-secret-key-here
   DB_HOST=localhost
   DB_NAME=pos_db
   DB_USER=your_database_username
   DB_PASSWORD=your_database_password
   ```

### Running the Application

1. Start the Flask server:
   ```
   python app.py
   ```

2. Open your browser and navigate to `http://localhost:5000`

3. Login with the default credentials (change immediately after first login):
   - Admin: username `admin`, password `admin123` (Super Admin — full access)
   - Cashier: username `cashier`, password `cashier123`

## Running as Executable

For easier distribution and use, the application can be packaged as a standalone Windows executable:

1. The executable includes all dependencies and can run on any Windows machine
2. No Python installation or database setup required (uses embedded SQLite for demo)
3. Simply double-click the executable to start the application
4. Access the application through your web browser at `http://localhost:5000`

To create the executable:
```
python build_pos.py
```

The executable will be created in the `dist` folder as `PointOfSale.exe`.

## Mobile Responsiveness

The application is fully optimized for mobile and tablet devices with:

- **Touch-friendly interface**: All interactive elements meet the 44px minimum touch target size
- **Responsive layouts**: Adapts smoothly to all screen sizes from desktop to mobile
- **Flexible navigation**: Collapsible menus and stacked layouts for small screens
- **Optimized forms**: Vertical layouts and proper spacing for mobile data entry
- **Responsive tables**: Horizontal scrolling for data tables on small screens
- **Performance optimized**: Lightweight implementation with no unnecessary assets

See `MOBILE_UI_IMPROVEMENTS.md` for detailed documentation of all mobile enhancements.

## Excel Data Upload Features

The Admin Panel includes powerful data upload capabilities:

### Product Upload
- Upload product information from Excel files
- Supports bulk import and update of products
- Template available for correct formatting
- SKU-based duplicate handling (updates existing products)

### Sales Data Upload
- Import historical sales data from Excel
- Maintains all GST calculation integrity
- Links to existing products automatically

### Purchase Data Upload
- Import purchase order history from Excel
- Updates inventory levels automatically
- Creates suppliers if they don't exist

## Project Structure

```
pos-system/
├── app.py              # Main Flask application
├── schema.sql          # Database schema
├── requirements.txt    # Python dependencies
├── .env                # Environment variables (create this file)
├── db.py               # Database connection utilities
├── auth.py             # Authentication utilities
├── routes/             # API route handlers
│   ├── __init__.py
│   ├── auth.py         # Authentication routes
│   ├── products.py     # Product management routes
│   ├── sales.py        # Sales transaction routes
│   ├── inventory.py    # Inventory management routes
│   ├── reports.py      # Reporting routes
│   ├── data_upload.py  # Excel data upload routes
│   └── admin.py        # Admin routes
├── index.html          # Main sales interface
├── login.html          # Login page
├── dashboard.html      # Dashboard with navigation
├── purchase.html       # Purchase/stock receiving
├── inventory.html      # Inventory management
├── reports.html        # Sales reporting
├── admin.html          # Admin panel
├── receipt.html        # Printable receipt template
├── styles.css          # Main stylesheet
├── sales.js            # Sales interface JavaScript
├── build_pos.py        # Executable builder script
├── create_templates.py # Excel template generator
└── templates/          # Excel templates
    ├── sales_template.xlsx
    ├── purchase_order_template.xlsx
    └── product_template.xlsx
```

## API Endpoints

### Authentication
- `POST /api/login` - User login
- `GET /api/users/me` - Get current user info

### Products
- `GET /api/products?q=<search>` - Search products
- `POST /api/products` - Create product (Admin only)
- `PUT /api/products/<id>` - Update product (Admin only)
- `DELETE /api/products/<id>` - Delete product (Admin only)

### Sales
- `POST /api/sales` - Create sales invoice
- `PUT /api/sales/<invoice_id>/cancel` - Cancel invoice (Admin only)

### Inventory
- `GET /api/inventory` - Get inventory levels
- `POST /api/inventory/update` - Update inventory (Admin only)

### Reports
- `GET /api/reports/sales?start_date=<>&end_date<>` - Get sales report

### Admin
- `GET /api/admin/users` - Get all users (Admin only)
- `POST /api/admin/users` - Create user (Admin only)
- `PUT /api/admin/users/<id>/reset-password` - Reset user password (Admin only)
- `GET /api/admin/invoices` - Get all invoices (Admin only)
- `POST /api/admin/upload-sales` - Upload sales data from Excel (Admin only)
- `POST /api/admin/upload-purchase` - Upload purchase data from Excel (Admin only)
- `POST /api/admin/upload-products` - Upload product data from Excel (Admin only)

### Data Templates
- `GET /templates/sales_template.xlsx` - Download sales template
- `GET /templates/purchase_order_template.xlsx` - Download purchase template
- `GET /templates/product_template.xlsx` - Download product template

## Security Features

- Passwords are hashed using passlib
- JWT tokens for session management
- Role-based access control (Admin/Cashier)
- Protected API endpoints with token verification

## Responsive Design

The frontend is built with responsive design principles using:
- CSS Flexbox and Grid
- Media queries for different screen sizes
- Mobile-friendly interface with touch optimization
- Relative units (rem, em, %) instead of fixed px sizes

## Documentation

Detailed documentation is available in:
- `SYSTEM_DOCUMENTATION.md` - Complete system documentation
- `PRODUCT_UPLOAD_README.md` - Product upload feature documentation
- `EXECUTABLE_README.md` - Executable creation and usage documentation
- `MOBILE_UI_IMPROVEMENTS.md` - Mobile UI enhancement documentation

## License

This project is for educational purposes. Feel free to modify and extend it for your needs.