import os
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin,LoginManager,login_user,logout_user,current_user,login_required
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from sqlalchemy import Integer, String, Float, ForeignKey
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from werkzeug.security import generate_password_hash, check_password_hash
from wtforms import StringField, SubmitField, PasswordField
from wtforms.validators import DataRequired, Email, Length
from safepay_python.safepay import Safepay
import time


load_dotenv()

app = Flask(__name__)

# -------------------------------- CONFIG --------------------------------
def get_db_uri() -> str:
    """Turn the Neon URL into one SQLAlchemy can use with the pg8000 driver.
    Neon gives: postgresql://user:pass@host/db?sslmode=require
    - the driver name must be postgresql+pg8000
    - pg8000 rejects the sslmode/channel_binding params, so the query string is
      dropped and SSL is switched on through ssl_context below instead.
    """
    url = make_url(os.environ["DATABASE_URL"])
    url = url.set(drivername="postgresql+pg8000", query={})
    return url.render_as_string(hide_password=False)


app.config["SECRET_KEY"] = os.getenv("CSRF")
app.config["WTF_CSRF_TIME_LIMIT"] = None
app.config["SQLALCHEMY_DATABASE_URI"] = get_db_uri()
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "connect_args": {
        "ssl_context": True,  # same as in testdb.py
        "timeout": 30,        # Neon may need a while to wake up from suspend
    },
    "pool_size": 3,           # small pool: light on an old, slow machine
    "max_overflow": 2,
    "pool_pre_ping": True,    # test a connection before using it
    "pool_recycle": 300,      # Neon drops idle connections, so refresh them
}
Bootstrap5(app)
# -------------------------------- PAYMENT GATEWAY --------------------------------
# Created once at module level so every route (e.g. /pay) can use it.
safepay = Safepay({
    "environment": "sandbox",
    "apiKey": os.getenv("API_KEY"),
    "v1Secret": os.getenv("SECRET_API_KEY"),
    "webhookSecret": os.getenv("WEBHOOK_SECRET"),
})


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

# -------------------------------- DATABASE -----------------------------

class Base(DeclarativeBase):
    pass
db = SQLAlchemy(model_class=Base)
db.init_app(app)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    email: Mapped[str] = mapped_column(String(250), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(250), nullable=False)


class Product(db.Model):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(50), nullable=False)
    img_url: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)


class Cart(db.Model):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    product = relationship("Product")


with app.app_context():
    db.create_all()

# -------------------------------- LOGIN MANAGER --------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # @login_required sends guests here

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# -------------------------------- HELPERS --------------------------------
def get_cart_items():
    return db.session.execute(
        db.select(Cart).where(Cart.user_id == current_user.id)
    ).scalars().all()


# -------------------------------- ROUTES --------------------------------
@app.route("/")
def home():
    return render_template("index.html", user=current_user)


@app.route("/signup", methods=["POST", "GET"])
def signup():
    reg_form = RegisterForm()
    if reg_form.validate_on_submit():
        email = reg_form.email.data.strip().lower()
        user = db.session.execute(db.select(User).where(User.email == email)).scalar()
        if user:
            flash("User already present. Try logging in.")
            return redirect(url_for("login"))

        # Explicit pbkdf2: newer Werkzeug defaults to scrypt, which needs a lot
        # of memory and may not be available on an old Python/OpenSSL build.
        hashed_password = generate_password_hash(
            reg_form.password.data, method="pbkdf2:sha256", salt_length=8
        )
        new_user = User(name=reg_form.name.data, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for("home"))

    return render_template("signup.html", user=current_user, form=reg_form)

@app.route("/login", methods=["POST", "GET"])
def login():
    login_form = LoginForm()
    if login_form.validate_on_submit():
        email = login_form.email.data.strip().lower()
        user = db.session.execute(db.select(User).where(User.email == email)).scalar()
        if not user:
            flash("Not found. Sign up instead.")
            return redirect(url_for("signup"))
        if not check_password_hash(user.password, login_form.password.data):
            flash("Incorrect password.")
        else:
            login_user(user)
            return redirect(url_for("home"))
    return render_template("login.html", user=current_user, form=login_form)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/search")
def search():
    searched_item = request.args.get("search", "").strip()
    products_list = db.session.execute(
        db.select(Product).where(Product.title.ilike(f"%{searched_item}%"))
    ).scalars().all()
    return render_template(
        "product.html", user=current_user, product_name=searched_item, items=products_list
    )


@app.route("/cart/add/<int:item_id>", methods=["POST"])
@login_required
def add_to_cart(item_id):
    if not current_user.is_authenticated:
        flash("Log in to add item to cart")
        return redirect(url_for("login"))
    product = db.get_or_404(Product, item_id)  # 404 if the product doesn't exist
    db.session.add(Cart(name=product.title, user_id=current_user.id, product_id=product.id))
    db.session.commit()
    flash(f"{product.title} added to cart ✓")
    return redirect(request.referrer or url_for("search"))


# ---------------------------------- CART PAGE --------------------------------------
@app.route("/cart")
@login_required
def my_cart():
    items = get_cart_items()
    total = sum(item.product.price for item in items)
    return render_template("cart.html", items=items, total=total, user=current_user)


@app.route("/cart/remove/<int:cart_id>", methods=["POST"])
@login_required
def remove_from_cart(cart_id):
    item = db.get_or_404(Cart, cart_id)
    if item.user_id != current_user.id:  # don't let users delete other people's items
        return redirect(url_for("my_cart"))
    db.session.delete(item)
    db.session.commit()
    flash("Item removed.")
    return redirect(url_for("my_cart"))


@app.route("/buy/<int:item_id>", methods=["POST"])
@login_required
def buy(item_id):
    # TODO: checkout logic
    return redirect(request.referrer or url_for("search"))


@app.route("/checkout")
@login_required
def checkout():
    items = get_cart_items()
    if not items:
        flash("Your cart is empty.")
        return redirect(url_for("my_cart"))
    total = sum(item.product.price for item in items)
    return render_template("checkout.html", items=items, total=total, user=current_user)

# ---------------------------------- PAYMENT ROUTES --------------------------------------
@app.route("/pay", methods=["POST"])
@login_required
def pay():
    items = get_cart_items()
    if not items:
        flash("Your cart is empty.")
        return redirect(url_for("my_cart"))

    total = sum(item.product.price for item in items)

    # Step 1: create a tracker token with the real cart total
    payment_response = safepay.set_payment_details({
        "amount": int(total),   # check Safepay docs: some gateways want the smallest unit (paisa -> int(total * 100))
        "currency": "PKR",
    })
    token = payment_response["data"]["token"]

    # Step 2: build the checkout URL
    base_url = request.host_url.rstrip("/")
    checkout_url = safepay.get_checkout_url({
        "beacon": token,
        "cancelUrl": f"{base_url}{url_for('checkout')}",
        "redirectUrl": f"{base_url}{url_for('payment_success')}",
        "orderId": f"ORDER-{current_user.id}-{int(time.time())}",
        "source": "custom",
        "webhooks": True,
    })

    # Step 3: send the customer to Safepay
    return redirect(checkout_url)


@app.route("/payment/success")
@login_required
def payment_success():
    # Clear the cart once the customer comes back from Safepay.
    # NOTE: for production, do this in /webhook after verifying Safepay's signature,
    # because anyone can open this URL directly.
    for item in get_cart_items():
        db.session.delete(item)
    db.session.commit()
    flash("Payment received. Thank you for your order!")
    return redirect(url_for("home"))


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(data)

    return {"status": "received"}, 200

# ------------------------------------------------------------------------
if __name__ == "__main__":
    app.run()

# TODO: 8. buy page
# TODO: 12. thankyou page
# TODO: 19. check inventory
