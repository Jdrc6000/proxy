from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return "This is home!"

@app.route("/drift")
def drift():
    return render_template("drifting_scratch.html")

app.run()
