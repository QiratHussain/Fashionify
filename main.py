from flask import Flask, render_template, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Float

app= Flask(__name__)
# -------------------------------- CONFIG --------------------------------


# -------------------------------- DATABASES --------------------------------
class Base(DeclarativeBase):
    pass

app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///products.db"
db = SQLAlchemy(model_class=Base)
db.init_app(app)


class Product(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(50),nullable=False)
    img_url: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)



with app.app_context():
    db.create_all()

# -------------------------------- ROUTES --------------------------------
@app.route("/", methods= ['POST','GET'])
def home():
    return render_template("index.html")


@app.route("/search")
def search():
    searched_item = request.args.get("search") 
    with app.app_context():
        products_list= db.session.execute(db.select(Product).where(Product.title == searched_item)).scalars().all()
        if products_list:
            return render_template("product.html", product_name= searched_item,items= products_list )
    return render_template("product.html", product_name=searched_item)

# ------------------------------------------------------------------------
if __name__=="__main__":
    app.run(debug=True)


# TODO: 3. users db
# TODO: 4. products db
# TODO: 5. users' products db
# TODO: 6. product page
# TODO: 7. not_found page
# TODO: 8. buy page
# TODO: 9. signup page
# TODO: 10. login page
# TODO: 11. checkout page
# TODO: 12. thankyou page
# TODO: 15. adjustable header
# TODO: 16. payment system
# TODO: 17. add_to_cart function
# TODO: 18. flexible searching
