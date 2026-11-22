from flask import Flask, render_template, redirect, url_for, request

app= Flask(__name__)
# -------------------------------- CONFIG --------------------------------

# -------------------------------- ROUTES --------------------------------
@app.route("/", methods= ['POST','GET'])
def home():
    return render_template("index.html")


@app.route("/search")
def search():
    searched_item = request.args.get("search") 
    print(searched_item)
    return render_template("index.html", searched_item=searched_item)

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
# TODO: 13. search option 
# TODO: 14. check for searched obj
# TODO: 15. adjustable header
# TODO: 16. payment system
# TODO: 17. add_to_cart function
