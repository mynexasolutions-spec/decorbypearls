from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_compress import Compress
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from slugify import slugify
from werkzeug.utils import secure_filename
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import cloudinary
import cloudinary.uploader

app = Flask(__name__)
# Enable Gzip compression for responses
Compress(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'decorbypearls-dev-secret-key'
# Using Supabase (Postgres) with a local SQLite fallback
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///site.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Caching settings: 1 year cache for static files
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Dynamic cache-busting: override url_for for static files to append file mtime
@app.context_processor
def override_url_for():
    return dict(url_for=dated_url_for)

def dated_url_for(endpoint, **values):
    if endpoint == 'static':
        filename = values.get('filename', None)
        if filename:
            file_path = os.path.join(app.static_folder, filename)
            if os.path.exists(file_path):
                values['v'] = int(os.stat(file_path).st_mtime)
    return url_for(endpoint, **values)

# Set Cache-Control headers per asset type
@app.after_request
def add_header(response):
    if request.path.startswith('/static/'):
        # CSS and JS change with deployments — URL versioning busts cache,
        # but DON'T use 'immutable' so hard-refresh can recover stale states.
        if request.path.endswith(('.css', '.js')):
            response.headers['Cache-Control'] = 'public, max-age=31536000'
        else:
            # Images, fonts, favicons — truly static, safe to mark immutable
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif response.content_type and response.content_type.startswith('text/html'):
        # HTML pages must always be fresh so browsers get the latest CSS/JS URLs
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
    return response


# Cloudinary Configuration
cloudinary.config( 
  cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
  api_key = os.environ.get('CLOUDINARY_API_KEY'), 
  api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
  secure = True
)

# Allowed extensions for local temp storage before Cloudinary
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):

    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# --- MODELS ---
class User(db.Model, UserMixin):
    __tablename__ = 'site_user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    blogs = db.relationship('Blog', backref='cat', lazy=True)

class Blog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.String(500))
    image_url = db.Column(db.String(500))
    tags = db.Column(db.String(200)) # Comma separated tags
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # SEO fields
    image_alt = db.Column(db.String(200))
    meta_title = db.Column(db.String(100))
    meta_description = db.Column(db.String(320))
    focus_keyword = db.Column(db.String(100))
    canonical_url = db.Column(db.String(500))

class Testimonial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100))
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, default=5)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ContactSubmission(db.Model):
    __tablename__ = 'contact_submission'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20))
    event_type = db.Column(db.String(50))
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def seed_db():
    # Initial Categories
    categories = ['Uncategorized', 'Planning Tips', 'Trends', 'Inspiration', 'Hospitality']
    for cat_name in categories:
        if not Category.query.filter_by(name=cat_name).first():
            db.session.add(Category(name=cat_name))
    db.session.commit()

    # Initial Blogs
    if Blog.query.count() == 0:
        from seed_data import INITIAL_BLOGS
        for b in INITIAL_BLOGS:
            cat = Category.query.filter_by(name=b['category']).first()
            blog = Blog(
                title=b['title'],
                slug=slugify(b['title']),
                content=b['content'].strip(),
                excerpt=b['excerpt'],
                image_url=b['image'],
                tags=b.get('tags', ''),
                category_id=cat.id if cat else None
            )
            db.session.add(blog)
    
    
    # Initial Testimonials
    if Testimonial.query.count() == 0:
        initial_testis = [
            {"name": "Priya Sharma", "role": "Udaipur Palace Wedding", "content": "Decor By Pearls turned our dream wedding into reality. Every detail was perfect, from the floral canopies to the palace lighting. They are the best in the business!", "status": "approved"},
            {"name": "Meera & Rahul Kapoor", "role": "Goa Beach Wedding", "content": "The team was incredibly professional and attentive. They understood our vision perfectly and executed it flawlessly. Our guests are still talking about the decor!", "status": "approved"},
            {"name": "Ananya Singh", "role": "Chandigarh Garden Wedding", "content": "From the very first consultation to the last dance, Decor By Pearls handled everything with grace. They made the entire planning process stress-free and beautiful.", "status": "approved"}
        ]
        for t in initial_testis:
            db.session.add(Testimonial(name=t['name'], role=t['role'], content=t['content'], status=t['status']))
    
    db.session.commit()

# Create tables and default user
from sqlalchemy import text
with app.app_context():
    db.create_all()
    # Check if we are using SQLite or PostgreSQL
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    is_sqlite = db_uri.startswith('sqlite:')

    # Migration: Add category_id and tags if they don't exist (Supabase/Postgres)
    # We skip these on SQLite because db.create_all() creates the correct schema from scratch,
    # and SQLite doesn't support this PostgreSQL syntax.
    if not is_sqlite:
        def run_migration(sql):
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                # We don't print everything to keep logs clean, but we know it might fail if already exists
                if "already exists" not in str(e).lower():
                    print(f"Migration notice for '{sql[:30]}...': {e}")

        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES category(id)")
        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS tags VARCHAR(200)")
        run_migration("ALTER TABLE blog DROP COLUMN IF EXISTS category")
        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS image_alt VARCHAR(200)")
        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS meta_title VARCHAR(100)")
        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS meta_description VARCHAR(320)")
        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS focus_keyword VARCHAR(100)")
        run_migration("ALTER TABLE blog ADD COLUMN IF NOT EXISTS canonical_url VARCHAR(500)")
        run_migration('ALTER TABLE IF EXISTS "user" RENAME TO site_user')
        run_migration('ALTER TABLE site_user ALTER COLUMN password TYPE VARCHAR(255)')
        run_migration('ALTER TABLE site_user ALTER COLUMN username TYPE VARCHAR(100)')
        run_migration("CREATE TABLE IF NOT EXISTS contact_submission (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, email VARCHAR(150) NOT NULL, phone VARCHAR(20), event_type VARCHAR(50), message TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW())")

    seed_db()
    # Create or update default admin
    admin_email = os.environ.get('ADMIN_USERNAME', 'ashishr730246@gmail.com')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'Decorbypearls@0302')
    user = User.query.filter_by(username=admin_email).first()
    if not user:
        hashed_pw = generate_password_hash(admin_pass)
        new_admin = User(username=admin_email, password=hashed_pw)
        db.session.add(new_admin)
        db.session.commit()
    else:
        # Update password for existing user if needed
        user.password = generate_password_hash(admin_pass)
        db.session.commit()


# --- AUTH ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('admin/login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

# --- PUBLIC ROUTES ---

@app.route('/')
def home():
    testimonials = Testimonial.query.filter_by(status='approved').order_by(Testimonial.created_at.desc()).limit(3).all()
    return render_template('pages/home.html', testimonials=testimonials)

@app.route('/about/')
def about():
    return render_template('pages/about.html')

@app.route('/services/complete-wedding-management/')
def services():
    return render_template('pages/services.html')

@app.route('/services/chandigarh/')
def chandigarh():
    return render_template('pages/chandigarh.html')

@app.route('/services/punjab/')
def punjab():
    return render_template('pages/punjab.html')

@app.route('/services/haryana/')
def haryana():
    return render_template('pages/haryana.html')

@app.route('/services/himachal/')
def himachal():
    return render_template('pages/himachal.html')

# 301 redirects from old URLs
@app.route('/services/')
def services_old():
    return redirect(url_for('services'), 301)

@app.route('/venues/chandigarh/')
def chandigarh_old():
    return redirect(url_for('chandigarh'), 301)

@app.route('/venues/punjab/')
def punjab_old():
    return redirect(url_for('punjab'), 301)

@app.route('/venues/haryana/')
def haryana_old():
    return redirect(url_for('haryana'), 301)

@app.route('/venues/himachal/')
def himachal_old():
    return redirect(url_for('himachal'), 301)

@app.route('/gallery/')
def gallery():
    return render_template('pages/gallery.html')

@app.route('/testimonials/')
def testimonials():
    approved_testimonials = Testimonial.query.filter_by(status='approved').order_by(Testimonial.created_at.desc()).all()
    return render_template('pages/testimonials.html', testimonials=approved_testimonials)

@app.route('/contact/', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        event_type = request.form.get('event_type', '').strip()
        message = request.form.get('message', '').strip()
        if name and email and message:
            submission = ContactSubmission(
                name=name, email=email, phone=phone,
                event_type=event_type, message=message
            )
            db.session.add(submission)
            db.session.commit()
        return redirect(url_for('contact') + '?success=1')
    success = request.args.get('success')
    return render_template('pages/contact.html', success=success)


@app.route('/robots.txt')
def robots_txt():
    content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /login
Disallow: /logout

Sitemap: https://www.decorbypearls.com/sitemap_index.xml
"""
    return Response(content, mimetype='text/plain')


# --- Sitemap helpers ---

def _url_entry(loc, lastmod, changefreq, priority):
    return (
        f"  <url>"
        f"<loc>{loc}</loc>"
        f"<lastmod>{lastmod}</lastmod>"
        f"<changefreq>{changefreq}</changefreq>"
        f"<priority>{priority}</priority>"
        f"</url>"
    )

def _urlset_response(entries):
    body = "\n".join(entries)
    return Response(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{body}\n'
        f'</urlset>',
        mimetype='application/xml'
    )


# --- Sitemap index (parent) ---

@app.route('/sitemap_index.xml')
def sitemap_index():
    today = datetime.utcnow().date().isoformat()
    base = 'https://www.decorbypearls.com'

    last_blog = Blog.query.order_by(Blog.created_at.desc()).first()
    blog_lastmod = last_blog.created_at.date().isoformat() if last_blog and last_blog.created_at else today

    sitemaps = [
        (f'{base}/page-sitemap.xml',    today),
        (f'{base}/service-sitemap.xml', today),
        (f'{base}/blog-sitemap.xml',    blog_lastmod),
    ]
    entries = "\n".join(
        f"  <sitemap><loc>{loc}</loc><lastmod>{lm}</lastmod></sitemap>"
        for loc, lm in sitemaps
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{entries}\n'
        '</sitemapindex>'
    )
    return Response(content, mimetype='application/xml')


# /sitemap.xml 301 → /sitemap_index.xml (keeps old GSC submissions working)
@app.route('/sitemap.xml')
def sitemap_xml():
    return redirect('https://www.decorbypearls.com/sitemap_index.xml', 301)


# --- Child sitemaps ---

@app.route('/page-sitemap.xml')
def page_sitemap():
    today = datetime.utcnow().date().isoformat()
    base = 'https://www.decorbypearls.com'
    pages = [
        (f'{base}/',              '1.0', 'daily'),
        (f'{base}/about/',        '0.7', 'monthly'),
        (f'{base}/gallery/',      '0.8', 'weekly'),
        (f'{base}/testimonials/', '0.7', 'weekly'),
        (f'{base}/contact/',      '0.7', 'monthly'),
        (f'{base}/blog/',         '0.8', 'daily'),
    ]
    entries = [_url_entry(loc, today, cf, pri) for loc, pri, cf in pages]
    return _urlset_response(entries)


@app.route('/service-sitemap.xml')
def service_sitemap():
    today = datetime.utcnow().date().isoformat()
    base = 'https://www.decorbypearls.com'
    pages = [
        (f'{base}/services/complete-wedding-management/', '0.9', 'weekly'),
        (f'{base}/services/chandigarh/',                '0.9', 'weekly'),
        (f'{base}/services/punjab/',                    '0.9', 'weekly'),
        (f'{base}/services/haryana/',                   '0.9', 'weekly'),
        (f'{base}/services/himachal/',                  '0.9', 'weekly'),
    ]
    entries = [_url_entry(loc, today, cf, pri) for loc, pri, cf in pages]
    return _urlset_response(entries)


@app.route('/blog-sitemap.xml')
def blog_sitemap():
    today = datetime.utcnow().date().isoformat()
    base = 'https://www.decorbypearls.com'
    posts = Blog.query.order_by(Blog.created_at.desc()).all()
    entries = [
        _url_entry(
            f"{base}/blog/{post.slug}/",
            post.created_at.date().isoformat() if post.created_at else today,
            'monthly',
            '0.8'
        )
        for post in posts
    ]
    return _urlset_response(entries)

@app.route('/submit-testimonial', methods=['POST'])
def submit_testimonial():
    name = request.form.get('name')
    role = request.form.get('role')
    content = request.form.get('content')
    rating = request.form.get('rating', 5)
    
    if name and content:
        new_testimonial = Testimonial(name=name, role=role, content=content, rating=int(rating))
        db.session.add(new_testimonial)
        db.session.commit()
        return jsonify({"status": "success", "message": "Thank you! Your testimonial has been submitted for review."})
    return jsonify({"status": "error", "message": "Please fill all required fields."}), 400

@app.route('/blog/')
def blog():
    cat_id = request.args.get('category', '')
    search_q = request.args.get('q', '').strip()
    
    query = Blog.query
    if cat_id:
        query = query.filter_by(category_id=cat_id)
    if search_q:
        search_term = f"%{search_q}%"
        query = query.filter(
            db.or_(
                Blog.title.ilike(search_term),
                Blog.excerpt.ilike(search_term),
                Blog.tags.ilike(search_term)
            )
        )
    blogs = query.order_by(Blog.created_at.desc()).all()
    categories = Category.query.all()
    return render_template('pages/blogs.html', blogs=blogs, categories=categories, selected_category=cat_id, search_query=search_q)

@app.route('/blog/<slug>/')
def blog_single(slug):
    post = Blog.query.filter_by(slug=slug).first_or_404()
    recent_posts = Blog.query.filter(Blog.slug != slug).order_by(Blog.created_at.desc()).limit(3).all()
    categories = Category.query.all()
    return render_template('pages/blog_single.html', post=post, recent_posts=recent_posts, categories=categories)

# --- ADMIN ROUTES ---

@app.route('/admin')
@login_required
def admin_dashboard():
    blog_count = Blog.query.count()
    pending_testimonials = Testimonial.query.filter_by(status='pending').count()
    return render_template('admin/dashboard.html', blog_count=blog_count, pending_count=pending_testimonials)

@app.route('/admin/blogs')
@login_required
def admin_blogs():
    blogs = Blog.query.order_by(Blog.created_at.desc()).all()
    categories = Category.query.all()
    return render_template('admin/manage_blogs.html', blogs=blogs, categories=categories)

@app.route('/admin/blog/new', methods=['GET', 'POST'])
@login_required
def new_blog():
    categories = Category.query.all()
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        excerpt = request.form.get('excerpt')
        category_id = request.form.get('category_id')
        
        # Handle Cloudinary Upload
        image_url = ''
        if 'featured_image' in request.files:
            file = request.files['featured_image']
            if file and allowed_file(file.filename):
                upload_result = cloudinary.uploader.upload(file, folder="blogs")
                image_url = upload_result.get('secure_url')
        
        slug = slugify(title)
        
        new_post = Blog(
            title=title,
            slug=slug,
            content=content,
            excerpt=excerpt,
            image_url=image_url,
            image_alt=request.form.get('image_alt', ''),
            tags=request.form.get('tags', ''),
            category_id=category_id,
            meta_title=request.form.get('meta_title', ''),
            meta_description=request.form.get('meta_description', ''),
            focus_keyword=request.form.get('focus_keyword', ''),
            canonical_url=request.form.get('canonical_url', '')
        )
        db.session.add(new_post)
        db.session.commit()
        flash('Blog post created successfully!', 'success')
        return redirect(url_for('admin_blogs'))
    
    return render_template('admin/blog_editor.html', title="New Blog Post", categories=categories)

@app.route('/admin/blog/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_blog(id):
    post = Blog.query.get_or_404(id)
    categories = Category.query.all()
    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        post.excerpt = request.form.get('excerpt')
        post.tags = request.form.get('tags', '')
        post.category_id = request.form.get('category_id')
        post.slug = slugify(post.title)
        post.image_alt = request.form.get('image_alt', '')
        post.meta_title = request.form.get('meta_title', '')
        post.meta_description = request.form.get('meta_description', '')
        post.focus_keyword = request.form.get('focus_keyword', '')
        post.canonical_url = request.form.get('canonical_url', '')
        
        # Handle Cloudinary Upload
        if 'featured_image' in request.files:
            file = request.files['featured_image']
            if file and allowed_file(file.filename):
                upload_result = cloudinary.uploader.upload(file, folder="blogs")
                post.image_url = upload_result.get('secure_url')
        
        db.session.commit()
        flash('Blog post updated successfully!', 'success')
        return redirect(url_for('admin_blogs'))
    
    return render_template('admin/blog_editor.html', title="Edit Blog Post", post=post, categories=categories)

@app.route('/admin/blog/delete/<int:id>')
@login_required
def delete_blog(id):
    post = Blog.query.get_or_404(id)
    db.session.delete(post)
    db.session.commit()
    flash('Blog post deleted.', 'info')
    return redirect(url_for('admin_blogs'))

@app.route('/admin/testimonials')
@login_required
def admin_testimonials():
    pending = Testimonial.query.filter_by(status='pending').order_by(Testimonial.created_at.desc()).all()
    approved = Testimonial.query.filter_by(status='approved').order_by(Testimonial.created_at.desc()).all()
    return render_template('admin/manage_testimonials.html', pending=pending, approved=approved)

@app.route('/admin/testimonial/approve/<int:id>')
@login_required
def approve_testimonial(id):
    t = Testimonial.query.get_or_404(id)
    t.status = 'approved'
    db.session.commit()
    flash('Testimonial approved!', 'success')
    return redirect(url_for('admin_testimonials'))

@app.route('/admin/testimonial/delete/<int:id>')
@login_required
def delete_testimonial(id):
    t = Testimonial.query.get_or_404(id)
    db.session.delete(t)
    db.session.commit()
    flash('Testimonial removed.', 'info')
    return redirect(url_for('admin_testimonials'))

# --- CATEGORY MANAGEMENT ---

@app.route('/admin/categories')
@login_required
def admin_categories():
    categories = Category.query.all()
    return render_template('admin/manage_categories.html', categories=categories)

@app.route('/admin/category/new', methods=['POST'])
@login_required
def new_category():
    name = request.form.get('name')
    if name:
        # Check if exists
        existing = Category.query.filter_by(name=name).first()
        if existing:
            flash('Category already exists.', 'warning')
        else:
            new_cat = Category(name=name)
            db.session.add(new_cat)
            db.session.commit()
            flash('Category added successfully!', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/category/delete/<int:id>')
@login_required
def delete_category(id):
    cat = Category.query.get_or_404(id)
    
    # Prevent deleting Uncategorized
    if cat.name == 'Uncategorized':
        flash('Cannot delete the default Uncategorized category.', 'danger')
        return redirect(url_for('admin_categories'))

    # Find Uncategorized category
    uncategorized = Category.query.filter_by(name='Uncategorized').first()
    if not uncategorized:
        # Fallback create if somehow missing
        uncategorized = Category(name='Uncategorized')
        db.session.add(uncategorized)
        db.session.commit()

    # Move all blogs to Uncategorized
    for blog in cat.blogs:
        blog.category_id = uncategorized.id
    
    db.session.delete(cat)
    db.session.commit()
    flash(f'Category deleted. All posts have been moved to Uncategorized.', 'info')
    return redirect(url_for('admin_categories'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=True, use_reloader=True)




