from jinja2 import Template

t = Template("<div data-lead=\"{{ lead | tojson | forceescape }}\"></div>")
print("DOUBLE QUOTES + FORCEESCAPE:")
print(t.render(lead={"name": "Jaybee's Valet Laundry"}))

t2 = Template("<div data-lead='{{ lead | tojson }}'></div>")
print("SINGLE QUOTES + TOJSON:")
print(t2.render(lead={"name": "Jaybee's Valet Laundry"}))

