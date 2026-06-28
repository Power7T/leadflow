from jinja2 import Template
t = Template("<div data-lead=\"{{ lead | tojson | e }}\"></div>")
print("DOUBLE QUOTES + e:")
print(t.render(lead={"name": "Jaybee's"}))
