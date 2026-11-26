import os
from dotenv import load_dotenv
import requests
from flask import Flask, render_template, redirect, url_for, request, flash, session
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
from safepay_python.utils.builder import build_api_url
from werkzeug.middleware.proxy_fix import ProxyFix
import time


load_dotenv()

app = Flask(__name__)
# Behind Vercel's proxy: trust X-Forwarded-* so url_for(_external=True) builds https:// URLs
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

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
SAFEPAY_ENV = "sandbox"   # change to "production" when you go live
safepay = Safepay({
    "environment": SAFEPAY_ENV,
    "apiKey": os.getenv("API_KEY") ,
    "v1Secret": os.getenv("SECRET_API_KEY"),
    "webhookSecret": os.getenv("WEBHOOK_SECRET"),
})

# # Step 1: Set payment details to get a tracker token
# payment_response = safepay.set_payment_details({
#     "amount": 10000,      # Amount (e.g., 10,000 PKR)
#     "currency": "PKR"     # Supported: "PKR" or "USD"
# })
# token = payment_response["data"]["token"]

# # Step 2: Generate the checkout URL
# checkout_url = safepay.get_checkout_url({
#     "beacon": token,
#     "cancelUrl": "https://fashionify-z8quguqn1-empire-e560.vercel.app/",
#     "redirectUrl": "https://fashionify-z8quguqn1-empire-e560.vercel.app/",
#     "orderId": "ORDER-101",  # Your internal order reference
#     "source": "custom",
#     "webhooks": True         # Enable webhook notifications
# })

# # Redirect the customer to `checkout_url`
# print("Redirect user to:", checkout_url)

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


@app.route("/buy/<int:item_id>", methods=["POST"])
@login_required
def buy(item_id):
    # "Buy" = put the item in the cart, then go straight to the cart page to pay
    product = db.get_or_404(Product, item_id)
    db.session.add(Cart(name=product.title, user_id=current_user.id, product_id=product.id))
    db.session.commit()
    return redirect(url_for("cart"))


@app.route("/cart")
@login_required
def cart():
    items = get_cart_items()
    total = round(sum(item.product.price for item in items), 2)
    return render_template("cart.html", items=items, total=total, user=current_user)


# Same page under the name `my_cart` too, so url_for('cart') and url_for('my_cart') both work
app.add_url_rule("/cart", endpoint="my_cart", view_func=cart)


@app.route("/checkout")
@login_required
def checkout():
    items = get_cart_items()
    if not items:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))
    total = round(sum(item.product.price for item in items), 2)
    return render_template("checkout.html", items=items, total=total, user=current_user)


# ---------------------------------- PAYMENT ROUTES --------------------------------------
def create_safepay_tracker(amount):
    """Ask Safepay for a tracker token for this amount.

    This calls Safepay's init endpoint directly instead of safepay.set_payment_details():
    the SDK runs asyncio.get_event_loop().run_until_complete(), which raises errors on
    modern Python / serverless (Vercel), so it was a likely source of 500s.
    """
    response = requests.post(
        f"{build_api_url(SAFEPAY_ENV)}/order/v1/init",
        json={
            "amount": amount,
            "client": os.getenv("API_KEY"),
            "currency": "PKR",
            "environment": SAFEPAY_ENV,
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["data"]["token"]


@app.route("/pay", methods=["POST"])
@login_required
def pay():
    items = get_cart_items()
    if not items:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    if not (os.getenv("API_KEY") and os.getenv("SECRET_API_KEY") and os.getenv("WEBHOOK_SECRET")):
        app.logger.error("Safepay env vars (API_KEY / SECRET_API_KEY / WEBHOOK_SECRET) are not set")
        flash("Payments are not set up yet. Please try again later.")
        return redirect(url_for("cart"))

    total = round(sum(item.product.price for item in items), 2)

    # Step 1: create a tracker token with the real cart total
    try:
        token = create_safepay_tracker(total)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        app.logger.exception("Safepay init failed")
        flash("Could not start the payment. Please try again.")
        return redirect(url_for("cart"))

    # Remember which tracker we issued so /payment/success only accepts that one
    session["safepay_tracker"] = token

    # Step 2: build the checkout URL
    checkout_url = safepay.get_checkout_url({
        "beacon": token,
        "cancelUrl": url_for("cart", _external=True),
        "redirectUrl": url_for("payment_success", _external=True),
        "orderId": f"ORDER-{current_user.id}-{int(time.time())}",
        "source": "custom",
        "webhooks": True,
    })

    # Step 3: send the customer to Safepay
    return redirect(checkout_url)


@app.route("/payment/success")
@login_required
def payment_success():
    expected_tracker = session.get("safepay_tracker")
    if not expected_tracker:
        # Nothing pending (e.g. page refreshed after a finished payment)
        return redirect(url_for("home"))

    sig = request.args.get("sig", "")
    tracker = request.args.get("tracker", "")
    if not (sig and tracker == expected_tracker
            and safepay.is_signature_valid({"sig": sig, "tracker": tracker})):
        flash("We couldn't confirm your payment. If you were charged, please contact support.")
        return redirect(url_for("cart"))

    # Payment confirmed: empty the cart and thank the customer
    items = get_cart_items()
    total = round(sum(item.product.price for item in items), 2)
    for item in items:
        db.session.delete(item)
    db.session.commit()
    session.pop("safepay_tracker", None)
    return render_template("thankyou.html", user=current_user, total=total)


@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json(silent=True)
    try:
        valid = body is not None and safepay.is_webhook_valid(request.headers, body)
    except (KeyError, TypeError):
        valid = False
    if not valid:
        return {"status": "invalid signature"}, 400

    app.logger.info("Safepay webhook: %s", body)
    return {"status": "received"}, 200

# ------------------------------------------------------------------------
if __name__ == "__main__":
    app.run()

# TODO: 8. buy page
# TODO: 12. thankyou page
# TODO: 19. check inventory
