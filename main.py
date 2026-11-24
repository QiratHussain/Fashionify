from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_user, logout_user, current_user, login_required 
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Float, ForeignKey
import os
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_wtf import FlaskForm
from wtforms import StringField,SubmitField, PasswordField
from wtforms.validators import DataRequired, Email, Length
from flask_bootstrap import Bootstrap5
import ssl
from urllib.parse import urlsplit, urlunsplit

load_dotenv()

app= Flask(__name__)
# -------------------------------- CONFIG --------------------------------
app.config["SECRET_KEY"] = os.getenv("CSRF")
app.config['WTF_CSRF_TIME_LIMIT'] = None  
Bootstrap5(app)


# -------------------------------- FORMS --------------------------------
class RegisterForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired()])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(8)])
    submit = SubmitField("Sign Me Up!")

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login!")

# -------------------------------- DATABASES -----------------------------
class Base(DeclarativeBase):
    pass

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL is not set.")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
app.config["SECRET_KEY"] = os.environ.get("CSRF", "change-me")

database_url = urlunsplit(urlsplit(database_url)._replace(query=""))

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
# Neon suspends idle compute and drops idle connections, so test each connection before use.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    # SSL is passed as an object instead of sslmode=require
    "connect_args": {"ssl_context": ssl.create_default_context()},
}
# Neon suspends idle compute and drops idle connections, so test each connection before use.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True, "pool_recycle": 300}
db = SQLAlchemy(model_class=Base)
db.init_app(app)

class User( UserMixin ,db.Model):
    __tablename__= "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    email: Mapped[str] = mapped_column(String(250),unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(250), nullable=False)

class Product(db.Model):
    __tablename__= "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(50),nullable=False)
    img_url: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)

class Cart(db.Model):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), nullable=False)
    product = relationship("Product")

with app.app_context():
    db.create_all()

# -------------------------------- LOGIN MANAGER --------------------------------

login_manager= LoginManager()
login_manager.init_app(app)
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# -------------------------------- ROUTES --------------------------------
@app.route("/", methods= ['POST','GET'])
def home():
    return render_template("index.html", user=current_user)

@app.route("/signup", methods=['POST','GET'])
def signup():
    reg_form= RegisterForm()
    if reg_form.validate_on_submit():
        with app.app_context():
            user= db.session.execute(db.select(User).where(User.email == reg_form.email.data )).scalar()
            if user:
                flash("User already present. Try Loggin In")
                return redirect(url_for("login"))
            else:
                hashed_and_salted_password = generate_password_hash(reg_form.password.data, method='pbkdf2:sha256', salt_length=8)
                new_user = User(name= reg_form.name.data, email= reg_form.email.data, password= hashed_and_salted_password)
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user)
                return redirect(url_for("home"))

    return render_template("signup.html",user= current_user ,form= reg_form)

@app.route("/login", methods=['POST','GET'])
def login():
    login_form= LoginForm()
    if login_form.validate_on_submit():
        user= db.session.execute(db.select(User).where(User.email == login_form.email.data )).scalar()
        if not user:
            flash("Not found. Sign up instead.")
            return redirect(url_for("signup"))
        elif not check_password_hash(user.password, login_form.password.data):
            flash("Incorrect Password.")
        else:
            login_user(user)
            return redirect(url_for("home"))
    return render_template("login.html",user= current_user, form= login_form)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route("/search")
def search():
    searched_item = request.args.get("search", "")
    products_list = db.session.execute(db.select(Product).where(Product.title.ilike(f"%{searched_item}%"))).scalars().all()
    return render_template("product.html",user= current_user, product_name=searched_item, items=products_list)

@app.route("/cart/add/<int:item_id>", methods=["POST"])
@login_required
def add_to_cart(item_id):
    product = db.get_or_404(Product, item_id)   # 404 if the product doesn't exist
    new_cart = Cart(name=product.title, user_id=current_user.id, product_id=product.id)
    db.session.add(new_cart)
    db.session.commit()
    flash(f"{product.title} added to cart ✓")
    return redirect(request.referrer or url_for("search"))

@app.route("/buy/<int:item_id>", methods=["POST"])
def buy(item_id):
    # TODO: checkout logic
    return redirect(request.referrer or url_for("search"))

@app.route("/cart")
@login_required
def cart():
    items = db.session.execute(
        db.select(Cart).where(Cart.user_id == current_user.id)
    ).scalars().all()
    return render_template("cart.html", items=items, user=current_user)

@app.route("/checkout")
@login_required
def checkout():
    items = db.session.execute(
        db.select(Cart).where(Cart.user_id == current_user.id)
    ).scalars().all()
    total = sum(item.product.price for item in items)
    return render_template("checkout.html", items=items, total=total, user= current_user)

# ------------------------------------------------------------------------
if __name__=="__main__":
    app.run(debug=True)


# TODO: 8. buy page
# TODO: 12. thankyou page
# TODO: 16. payment system
# TODO: 19. check inventory
