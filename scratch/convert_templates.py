import os
import re

demo_templates_dir = "/Users/chandan/leadflow/demo_templates"

def convert_roofer():
    path = os.path.join(demo_templates_dir, "roofer.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Title and headers
    html = html.replace("<title>ALIO Fitness Club | Elevate Your Performance</title>", 
                        "<title>{{ lead.name }} | Austin's Premier Roofing Specialists</title>")
    html = html.replace('<meta name="description" content="Welcome to ALIO Fitness Club. Premium fitness facility in San Antonio.">',
                        '<meta name="description" content="Welcome to {{ lead.name }}. Premium roofing service contractor offering installations, repairs, and gutters in {{ lead.city or \'Austin\' }}.">')

    # 2. Hero Background image
    html = html.replace("url('https://pms5566.github.io/Iron-Peak-Gym/images/hero-bg.png')", "url('{{ hero_img }}')")
    html = html.replace('src="https://pms5566.github.io/Iron-Peak-Gym/images/about.png"', 'src="{{ about_img }}"')

    # 3. Demo banner
    banner_old = """<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for ALIO Fitness Club by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/sellers/chandangosavi/" target="_blank">hire me to take it live &rarr;</a>
  <span class="orig">Based on http://www.aliofitnessclubs.com</span>
</div>"""
    banner_new = """<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for {{ lead.name }} by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/sellers/chandangosavi/" target="_blank">hire me to take it live &rarr;</a>
  {% if lead.website %}
  <span class="orig">Based on <a href="http://{{ lead.website }}" target="_blank" style="color:inherit; text-decoration:underline;">http://www.{{ lead.website }}</a></span>
  {% endif %}
</div>"""
    html = html.replace(banner_old, banner_new)

    # 4. Brand Names
    html = html.replace("ALIO Fitness Club", "{{ lead.name }}")
    html = html.replace("ALIO FITNESS CLUB", "{{ lead.name | upper }}")
    html = html.replace("ALIO<span>FITNESS CLUB</span>", "{{ lead.name }}")

    # 5. Core copy
    html = html.replace("ALIO Fitness Club is a modern boutique gym offering expert-led group personal training and one-on-one personal training in San Antonio, TX.",
                        "{{ lead.name }} is a modern professional roofing contractor offering residential roof installations, emergency leak repairs, and commercial roofing services in {{ lead.city or 'Austin, TX' }}.")
    html = html.replace("ALIO Fitness Club is a modern boutique gym offering expert-led group personal training and one-on-one personal training in San Antonio, TX",
                        "{{ lead.name }} is a modern professional roofing contractor offering residential roof installations, emergency leak repairs, and commercial roofing services in {{ lead.city or 'Austin, TX' }}.")
    html = html.replace("A premier fitness facility committed to building strength, endurance, and an unstoppable mindset in San Antonio",
                        "A premier roofing contractor committed to building durable, leak-proof roofs with high-grade shingles and expert craftsmanship in {{ lead.city or 'Austin, TX' }}")
    html = html.replace("Redefine Your Limits", "Premium Roofing Services")
    html = html.replace("CONTACT US.", "ROOF INSTALL.")
    html = html.replace("INNER BEAST", "LEAK REPAIR")
    html = html.replace("TRUE POTENTIAL", "GET ESTIMATE")
    html = html.replace("Explore Programs", "Explore Services")
    html = html.replace("Who We Are", "Our Commitment")
    html = html.replace("Where Strength Is<br><span class=\"text-gradient-orange\">Forged</span> &amp; Limits Shattered",
                        "Where Quality Roofs Are<br><span class=\"text-gradient-orange\">Built</span> &amp; Homes Protected")
    html = html.replace("Start Your Journey at<br><span class=\"text-gradient-orange\">{{ lead.name }}</span> Today",
                        "Get Your Free Estimate from<br><span class=\"text-gradient-orange\">{{ lead.name }}</span> Today")
    html = html.replace("Want this site live for <b>{{ lead.name }}</b>?",
                        "Want this site live for <b>{{ lead.name }}</b>?")
    html = html.replace("Like this design for <b>ALIO Fitness Club</b>?",
                        "Like this design for <b>{{ lead.name }}</b>?")
    html = html.replace("Like this design for <b>{{ lead.name }}</b>?",
                        "Like this design for <b>{{ lead.name }}</b>?")

    # 6. Contact Details
    html = html.replace('href="tel:+1 210-490-2546"', 'href="tel:{{ lead.phone }}"')
    html = html.replace('📞 +1 210-490-2546', '📞 {{ lead.phone }}')
    html = html.replace('href="mailto:info@aliofitnessclubs.com"', 'href="mailto:{{ lead.email or \'contact@\' + lead.website }}"')
    html = html.replace('✉ info@aliofitnessclubs.com', '✉ {{ lead.email or \'contact@\' + lead.website }}')
    html = html.replace('📍 15909 San Pedro Ave #116', "📍 {{ lead.address or 'Austin, TX' }}")

    # 7. Services/Programs section
    programs_old = '<div class="programs-grid"><div class="program-card reveal reveal-slide-up" style=""><div class="program-icon">🏋️</div><h3>Strength Training</h3><p>Build muscle and power through progressive overload and compound movements.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s"><div class="program-icon">🔥</div><h3>HIIT & Cardio</h3><p>Torch fat and boost cardiovascular fitness with high-intensity circuits.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s"><div class="program-icon">🥊</div><h3>Personal Training</h3><p>One-on-one coaching sessions tailored entirely to your body and goals.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style=""><div class="program-icon">🧘</div><h3>Yoga & Recovery</h3><p>Improve flexibility and restore your body between intense training sessions.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s"><div class="program-icon">🏃</div><h3>Group Classes</h3><p>High-energy group sessions that push you further than training alone.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s"><div class="program-icon">💪</div><h3>Nutrition Coaching</h3><p>Expert nutrition plans to fuel performance and maximise your results.</p><a href="#contact" class="program-link">Get Started →</a></div></div>'
    
    programs_new = """<div class="programs-grid">
        <div class="program-card reveal reveal-slide-up" style="">
          <div class="program-icon">🏠</div>
          <h3>Roof Installation</h3>
          <p>High-quality residential roof replacements with premium shingles and lifetime warranties.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
          <div class="program-icon">🛠️</div>
          <h3>Roof Repair & Leaks</h3>
          <p>Fast, reliable leak repairs, storm damage mitigation, and emergency patching.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
          <div class="program-icon">🏢</div>
          <h3>Commercial Roofing</h3>
          <p>Durable, energy-efficient flat roof installations and coatings for commercial buildings.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="">
          <div class="program-icon">🌊</div>
          <h3>Gutter Services</h3>
          <p>Seamless aluminum gutter installations, leaf guards, and downspout tune-ups.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
          <div class="program-icon">📋</div>
          <h3>Roof Inspections</h3>
          <p>Thorough visual and digital drone inspections with reports for insurance claims.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
          <div class="program-icon">🔨</div>
          <h3>Siding & Trim</h3>
          <p>Enhance your curb appeal and protect your home with high-durability siding installation.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
      </div>"""
    html = html.replace(programs_old, programs_new)
    
    # Tag replacement
    html = html.replace('<span class="section-tag">Our Programs</span>', '<span class="section-tag">Our Services</span>')
    html = html.replace('Discover programs structured to improve strength, conditioning, agility and mental resilience.',
                        'Explore our comprehensive range of residential and commercial roofing services built to withstand the elements.')

    # 8. Testimonials
    testimonials_old = """        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Joining ALIO Fitness Club was the best decision I made. The coaches are incredible and the equipment is top-notch. I've seen results I never thought possible."</p>
          <div class="t-author">Sarah M.<span>Member since 2023</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"The atmosphere at ALIO Fitness Club is unmatched. Everyone is motivated and the trainers really push you to your limits while keeping it safe and fun."</p>
          <div class="t-author">James K.<span>Member since 2022</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"I've tried many gyms but ALIO Fitness Club is on a different level. The personal training sessions changed my physique completely in just 6 months."</p>
          <div class="t-author">Priya R.<span>Member since 2024</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Best investment I've made in my health. The group classes are energetic, the staff is supportive and the facilities are always clean and modern."</p>
          <div class="t-author">Ahmed N.<span>Member since 2023</span></div>
        </div>"""

    testimonials_new = """        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Hiring {{ lead.name }} was the best decision we made. The crew was professional, cleaned up daily, and our new roof looks incredible. Highly recommended!"</p>
          <div class="t-author">Sarah M.<span>Homeowner</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"The response speed from {{ lead.name }} was unmatched. They came out same-day for a roof leak, patched it quickly, and helped walk us through our insurance claim process."</p>
          <div class="t-author">James K.<span>Austin Resident</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"I've used several local contractors over the years, but {{ lead.name }} is on a different level. Honest pricing, exceptional roofing work, and zero clean-up issues."</p>
          <div class="t-author">Priya R.<span>Property Manager</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Best investment I've made on our property. The estimate was accurate, work was completed on time, and their warranty gives us total peace of mind."</p>
          <div class="t-author">Ahmed N.<span>Homeowner</span></div>
        </div>"""
    html = html.replace(testimonials_old, testimonials_new)
    
    html = html.replace('<span class="section-tag">What Members Say</span>', '<span class="section-tag">What Homeowners Say</span>')
    html = html.replace('Real Stories, Real Results', 'Recent Customer Reviews')
    html = html.replace('Member since 2023', 'Customer')
    html = html.replace('Member since 2022', 'Customer')
    html = html.replace('Member since 2024', 'Customer')

    # Remove dynamic preview customizer script since Jinja handles rendering
    html = re.sub(r'<!-- DYNAMIC PREVIEW CUSTOMIZATION SCRIPT -->.*?<!-- TRACKING SCRIPT -->', '<!-- TRACKING SCRIPT -->', html, flags=re.DOTALL)
    
    # 9. Update tracking beacons
    html = html.replace('bid="102"', 'bid="{{ lead.id }}"')
    html = html.replace('bid=102', 'bid={{ lead.id }}')
    html = html.replace('BID="102"', 'BID="{{ lead.id }}"')
    html = html.replace('https://patients-cnet-fcc-residence.trycloudflare.com', '{{ tracking_beacon_url or "" }}')
    
    # 10. Update footer credit
    html = html.replace('info@aliofitnessclubs.com', '{{ lead.email or \'contact@\' + lead.website }}')
    html = html.replace('Based on http://www.aliofitnessclubs.com', '')

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("Roofer template converted.")


def convert_hvac():
    path = os.path.join(demo_templates_dir, "hvac.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Title and headers
    html = html.replace("<title>Eden Fitness Studio | Elevate Your Performance</title>", 
                        "<title>{{ lead.name }} | Heating, Cooling & AC Repair Specialists</title>")
    html = html.replace('<meta name="description" content="Welcome to Eden Fitness Studio. Premium fitness facility in San Antonio.">',
                        '<meta name="description" content="Welcome to {{ lead.name }}. Certified local HVAC heating and cooling contractor in {{ lead.city or \'Austin\' }}.">')

    # 2. Hero Background image
    html = html.replace("url('https://pms5566.github.io/Iron-Peak-Gym/images/hero-bg.png')", "url('{{ hero_img }}')")
    html = html.replace('src="https://pms5566.github.io/Iron-Peak-Gym/images/about.png"', 'src="{{ about_img }}"')

    # 3. Demo banner
    banner_old = """<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for Eden Fitness Studio by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/sellers/chandangosavi/" target="_blank">hire me to take it live &rarr;</a>
  <span class="orig">Based on http://www.aliofitnessclubs.com</span>
</div>"""
    banner_new = """<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for {{ lead.name }} by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/sellers/chandangosavi/" target="_blank">hire me to take it live &rarr;</a>
  {% if lead.website %}
  <span class="orig">Based on <a href="http://{{ lead.website }}" target="_blank" style="color:inherit; text-decoration:underline;">http://www.{{ lead.website }}</a></span>
  {% endif %}
</div>"""
    html = html.replace(banner_old, banner_new)

    # 4. Brand Names
    html = html.replace("Eden Fitness Studio", "{{ lead.name }}")
    html = html.replace("Eden Fitness", "{{ lead.name }}")
    html = html.replace("Eden", "{{ lead.name }}")

    # 5. Core copy
    html = html.replace("boutique gym offering expert-led group personal training and one-on-one personal training in San Antonio, TX",
                        "professional heating & cooling company offering expert AC installations, emergency HVAC repairs, indoor air quality checks, and seasonal furnace tuning in {{ lead.city or 'Austin, TX' }}.")
    html = html.replace("boutique gym offering expert-led group personal training and one-on-one personal training in San Antonio, TX.",
                        "professional heating & cooling company offering expert AC installations, emergency HVAC repairs, indoor air quality checks, and seasonal furnace tuning in {{ lead.city or 'Austin, TX' }}.")
    html = html.replace("A premier fitness facility committed to building strength, endurance, and an unstoppable mindset in San Antonio",
                        "A premier heating & cooling company committed to providing superior home comfort and energy-efficient HVAC systems in {{ lead.city or 'Austin, TX' }}")
    html = html.replace("Redefine Your Limits", "Professional HVAC Services")
    html = html.replace("CONTACT US.", "AC SERVICE")
    html = html.replace("INNER BEAST", "HEATING REPAIR")
    html = html.replace("TRUE POTENTIAL", "EMERGENCY CALL")
    html = html.replace("Explore Programs", "Explore Services")
    html = html.replace("Who We Are", "Our Experts")
    html = html.replace("Where Strength Is<br><span class=\"text-gradient-orange\">Forged</span> &amp; Limits Shattered",
                        "Where Home Comfort Is<br><span class=\"text-gradient-orange\">Restored</span> &amp; Bills Reduced")
    html = html.replace("Start Your Journey at<br><span class=\"text-gradient-orange\">{{ lead.name }}</span> Today",
                        "Schedule AC Repair or Tune-Up with<br><span class=\"text-gradient-orange\">{{ lead.name }}</span> Today")
    html = html.replace("Want this site live for <b>{{ lead.name }}</b>?",
                        "Want this site live for <b>{{ lead.name }}</b>?")
    html = html.replace("Like this design for <b>Eden Fitness Studio</b>?",
                        "Like this design for <b>{{ lead.name }}</b>?")

    # 6. Contact Details
    html = html.replace('href="tel:+1 210-490-2546"', 'href="tel:{{ lead.phone }}"')
    html = html.replace('📞 +1 210-490-2546', '📞 {{ lead.phone }}')
    html = html.replace('href="mailto:info@aliofitnessclubs.com"', 'href="mailto:{{ lead.email or \'contact@\' + lead.website }}"')
    html = html.replace('✉ info@aliofitnessclubs.com', '✉ {{ lead.email or \'contact@\' + lead.website }}')
    html = html.replace('📍 15909 San Pedro Ave #116', "📍 {{ lead.address or 'Austin, TX' }}")

    # 7. Services/Programs section
    programs_old = '<div class="programs-grid"><div class="program-card reveal reveal-slide-up" style=""><div class="program-icon">🏋️</div><h3>Strength Training</h3><p>Build muscle and power through progressive overload and compound movements.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s"><div class="program-icon">🔥</div><h3>HIIT & Cardio</h3><p>Torch fat and boost cardiovascular fitness with high-intensity circuits.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s"><div class="program-icon">🥊</div><h3>Personal Training</h3><p>One-on-one coaching sessions tailored entirely to your body and goals.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style=""><div class="program-icon">🧘</div><h3>Yoga & Recovery</h3><p>Improve flexibility and restore your body between intense training sessions.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s"><div class="program-icon">🏃</div><h3>Group Classes</h3><p>High-energy group sessions that push you further than training alone.</p><a href="#contact" class="program-link">Get Started →</a></div><div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s"><div class="program-icon">💪</div><h3>Nutrition Coaching</h3><p>Expert nutrition plans to fuel performance and maximise your results.</p><a href="#contact" class="program-link">Get Started →</a></div></div>'
    
    programs_new = """<div class="programs-grid">
        <div class="program-card reveal reveal-slide-up" style="">
          <div class="program-icon">❄️</div>
          <h3>AC Installation</h3>
          <p>Energy-efficient air conditioning systems installed by certified HVAC experts with long-term warranties.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
          <div class="program-icon">🔧</div>
          <h3>AC Repair & Tune-ups</h3>
          <p>Rapid diagnostics, refrigerant leak checks, compressor repairs, and seasonal AC maintenance.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
          <div class="program-icon">🔥</div>
          <h3>Heating Services</h3>
          <p>Furnace repairs, heat pump installations, thermostat wiring, and heating system safety checks.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="">
          <div class="program-icon">🍃</div>
          <h3>Indoor Air Quality</h3>
          <p>Whole-house filtration systems, UV air purifiers, humidifiers, and duct cleaning inspections.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
          <div class="program-icon">🏢</div>
          <h3>Commercial HVAC</h3>
          <p>Reliable commercial heating and cooling installations and preventive maintenance for businesses.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
          <div class="program-icon">🚨</div>
          <h3>Emergency Service</h3>
          <p>24/7 rapid dispatch for emergency heating or cooling breakdowns to restore your home comfort fast.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
      </div>"""
    html = html.replace(programs_old, programs_new)
    
    # Tag replacement
    html = html.replace('<span class="section-tag">Our Programs</span>', '<span class="section-tag">Our Services</span>')
    html = html.replace('Discover programs structured to improve strength, conditioning, agility and mental resilience.',
                        'Explore our expert AC and heating services designed to keep your home comfortable and utility bills low.')

    # 8. Testimonials
    testimonials_old = """        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Joining Eden Fitness Studio was the best decision I made. The coaches are incredible and the equipment is top-notch. I've seen results I never thought possible."</p>
          <div class="t-author">Sarah M.<span>Member since 2023</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"The atmosphere at Eden Fitness Studio is unmatched. Everyone is motivated and the trainers really push you to your limits while keeping it safe and fun."</p>
          <div class="t-author">James K.<span>Member since 2022</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"I've tried many gyms but Eden Fitness Studio is on a different level. The personal training sessions changed my physique completely in just 6 months."</p>
          <div class="t-author">Priya R.<span>Member since 2024</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Best investment I've made in my health. The group classes are energetic, the staff is supportive and the facilities are always clean and modern."</p>
          <div class="t-author">Ahmed N.<span>Member since 2023</span></div>
        </div>"""

    testimonials_new = """        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Hiring {{ lead.name }} was the best decision we made. Our AC went out on a 100-degree Sunday and they had a technician out and our home cool within 2 hours!"</p>
          <div class="t-author">Sarah M.<span>Homeowner</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"The technicians from {{ lead.name }} were incredibly professional. They replaced our entire HVAC unit, cleaned up everything, and our energy bills have already dropped 20%."</p>
          <div class="t-author">James K.<span>Austin Resident</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"I've used several local contractors over the years, but {{ lead.name }} is on a different level. Honest pricing, highly knowledgeable technicians, and great customer care."</p>
          <div class="t-author">Priya R.<span>Property Owner</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Outstanding experience. The technician diagnosed the furnace issue in 10 minutes and had the replacement part in their van. Highly recommend!"</p>
          <div class="t-author">Ahmed N.<span>Homeowner</span></div>
        </div>"""
    html = html.replace(testimonials_old, testimonials_new)
    
    html = html.replace('<span class="section-tag">What Members Say</span>', '<span class="section-tag">What Homeowners Say</span>')
    html = html.replace('Real Stories, Real Results', 'Recent Customer Reviews')

    # Remove dynamic preview customizer script since Jinja handles rendering
    html = re.sub(r'<!-- DYNAMIC PREVIEW CUSTOMIZATION SCRIPT -->.*?<!-- TRACKING SCRIPT -->', '<!-- TRACKING SCRIPT -->', html, flags=re.DOTALL)
    
    # 9. Update tracking beacons
    html = html.replace('bid="119"', 'bid="{{ lead.id }}"')
    html = html.replace('bid=119', 'bid={{ lead.id }}')
    html = html.replace('BID="119"', 'BID="{{ lead.id }}"')
    html = html.replace('https://lived-britney-herself-calendar.trycloudflare.com', '{{ tracking_beacon_url or "" }}')
    
    # 10. Update footer credit
    html = html.replace('info@aliofitnessclubs.com', '{{ lead.email or \'contact@\' + lead.website }}')
    html = html.replace('Based on http://www.aliofitnessclubs.com', '')

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("HVAC template converted.")


def convert_solar():
    path = os.path.join(demo_templates_dir, "solar.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Title and headers
    html = html.replace("<title>ALIO Fitness Club | Elevate Your Performance</title>", 
                        "<title>{{ lead.name }} | Premium Solar Panel & Energy Solutions</title>")
    html = html.replace("<title>Rain City Fit | Elevate Your Performance</title>", 
                        "<title>{{ lead.name }} | Premium Solar Panel & Energy Solutions</title>")
    html = html.replace('<meta name="description" content="Welcome to ALIO Fitness Club. Premium fitness facility in San Antonio.">',
                        '<meta name="description" content="Welcome to {{ lead.name }}. Professional solar installer and clean energy contractor in {{ lead.city or \'Austin\' }}.">')
    html = html.replace('<meta name="description" content="Welcome to Rain City Fit. Premium fitness facility in Seattle.">',
                        '<meta name="description" content="Welcome to {{ lead.name }}. Professional solar installer and clean energy contractor in {{ lead.city or \'Austin\' }}.">')

    # 2. Hero Background image
    html = html.replace("url('https://pms5566.github.io/Iron-Peak-Gym/images/hero-bg.png')", "url('{{ hero_img }}')")
    html = html.replace('src="https://pms5566.github.io/Iron-Peak-Gym/images/about.png"', 'src="{{ about_img }}"')

    # 3. Demo banner
    banner_old = """<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for Rain City Fit by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/sellers/chandangosavi/" target="_blank">hire me to take it live &rarr;</a>
  <span class="orig">Based on http://www.aliofitnessclubs.com</span>
</div>"""
    banner_new = """<!-- Demo banner -->
<div class="demo-banner">
  ✨ FREE demo built for {{ lead.name }} by Chandan Gosavi &mdash;
  <a href="https://www.fiverr.com/sellers/chandangosavi/" target="_blank">hire me to take it live &rarr;</a>
  {% if lead.website %}
  <span class="orig">Based on <a href="http://{{ lead.website }}" target="_blank" style="color:inherit; text-decoration:underline;">http://www.{{ lead.website }}</a></span>
  {% endif %}
</div>"""
    html = html.replace(banner_old, banner_new)

    # 4. Brand Names
    html = html.replace("Rain City Fit", "{{ lead.name }}")
    html = html.replace("RAIN CITY FIT", "{{ lead.name | upper }}")

    # 5. Core copy
    html = html.replace("boutique gym offering expert-led group personal training and one-on-one personal training in San Antonio, TX",
                        "professional solar energy contractor offering custom residential panel installations, commercial solar integration, and high-efficiency backup battery systems in {{ lead.city or 'Austin, TX' }}.")
    html = html.replace("boutique gym offering expert-led group personal training and one-on-one personal training in San Antonio, TX.",
                        "professional solar energy contractor offering custom residential panel installations, commercial solar integration, and high-efficiency backup battery systems in {{ lead.city or 'Austin, TX' }}.")
    html = html.replace("A premier fitness facility committed to building strength, endurance, and an unstoppable mindset in San Antonio",
                        "A premier solar installer committed to helping homes transition to clean, reliable, and affordable solar energy in {{ lead.city or 'Austin, TX' }}")
    html = html.replace("Redefine Your Limits", "Go Solar & Save On Energy")
    html = html.replace("CONTACT US.", "SOLAR QUOTE")
    html = html.replace("INNER BEAST", "BATTERY STORAGE")
    html = html.replace("TRUE POTENTIAL", "GRID INTEGRATION")
    html = html.replace("Explore Programs", "Explore Services")
    html = html.replace("Who We Are", "Our Clean Energy")
    html = html.replace("Where Strength Is<br><span class=\"text-gradient-orange\">Forged</span> &amp; Limits Shattered",
                        "Where Clean Power Is<br><span class=\"text-gradient-orange\">Generated</span> &amp; Grids Unlocked")
    html = html.replace("Start Your Journey at<br><span class=\"text-gradient-orange\">{{ lead.name }}</span> Today",
                        "Claim Your Free Solar Savings Assessment from<br><span class=\"text-gradient-orange\">{{ lead.name }}</span> Today")
    html = html.replace("Want this site live for <b>{{ lead.name }}</b>?",
                        "Want this site live for <b>{{ lead.name }}</b>?")
    html = html.replace("Like this design for <b>Rain City Fit</b>?",
                        "Like this design for <b>{{ lead.name }}</b>?")

    # 6. Contact Details
    html = html.replace('href="tel:+1 206-555-0199"', 'href="tel:{{ lead.phone }}"')
    html = html.replace('📞 +1 206-555-0199', '📞 {{ lead.phone }}')
    html = html.replace('href="mailto:contact@raincityfit.com"', 'href="mailto:{{ lead.email or \'info@\' + lead.website }}"')
    html = html.replace('✉ contact@raincityfit.com', '✉ {{ lead.email or \'info@\' + lead.website }}')
    html = html.replace('📍 1200 E Pike St, Seattle', "📍 {{ lead.address or 'Austin, TX' }}")

    # 7. Services/Programs section
    programs_old = """    <div class="programs-grid">
        <div class="program-card reveal reveal-slide-up">
        <div class="program-icon">🏋️</div>
        <h3>Strength Training</h3>
        <p>Build muscle and power through progressive overload and compound movements.</p>
        <a href="#contact" class="program-link">Get Started →</a></div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
        <div class="program-icon">🔥</div>
        <h3>HIIT & Cardio</h3>
        <p>Torch fat and boost cardiovascular fitness with high-intensity circuits.</p>
        <a href="#contact" class="program-link">Get Started →</a></div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
        <div class="program-icon">🥊</div>
        <h3>Personal Training</h3>
        <p>One-on-one coaching sessions tailored entirely to your body and goals.</p>
        <a href="#contact" class="program-link">Get Started →</a></div>
    </div>"""
    
    programs_new = """<div class="programs-grid">
        <div class="program-card reveal reveal-slide-up" style="">
          <div class="program-icon">☀️</div>
          <h3>Residential Solar</h3>
          <p>Custom-designed solar panel systems tailored to maximize sun exposure and slash electricity bills.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
          <div class="program-icon">🔋</div>
          <h3>Battery Backups</h3>
          <p>Seamless battery storage integration to power your home during outages and offset peak rates.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
          <div class="program-icon">🏢</div>
          <h3>Commercial Solar</h3>
          <p>Scalable clean energy systems designed to dramatically lower operating overhead costs for businesses.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="">
          <div class="program-icon">🪛</div>
          <h3>Maintenance & Repairs</h3>
          <p>Professional solar panel cleanings, diagnostics, panel upgrades, and efficiency audits.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.1s">
          <div class="program-icon">📋</div>
          <h3>Roof Assessments</h3>
          <p>Comprehensive inspection of your roof structure to ensure a safe, long-lasting solar installation.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
        <div class="program-card reveal reveal-slide-up" style="transition-delay:0.2s">
          <div class="program-icon">🌐</div>
          <h3>Net Metering Setup</h3>
          <p>Hook up your system to the grid and automatically sell your excess solar generation back to the utility company.</p>
          <a href="#contact" class="program-link">Get Free Quote →</a>
        </div>
      </div>"""
    html = html.replace(programs_old, programs_new)
    
    # Tag replacement
    html = html.replace('<span class="section-tag">Our Programs</span>', '<span class="section-tag">Our Services</span>')
    html = html.replace('Discover programs structured to improve strength, conditioning, agility and mental resilience.',
                        'Explore our custom-engineered solar services designed to maximize your energy savings and protect your home power grid.')

    # 8. Testimonials
    testimonials_old = """        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Joining Rain City Fit was the best decision I made. The coaches are incredible and the equipment is top-notch. I've seen results I never thought possible."</p>
          <div class="t-author">Sarah M.<span>Member since 2023</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"The atmosphere at Rain City Fit is unmatched. Everyone is motivated and the trainers really push you to your limits while keeping it safe and fun."</p>
          <div class="t-author">James K.<span>Member since 2022</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"I've tried many gyms but Rain City Fit is on a different level. The personal training sessions changed my physique completely in just 6 months."</p>
          <div class="t-author">Priya R.<span>Member since 2024</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Best investment I've made in my health. The group classes are energetic, the staff is supportive and the facilities are always clean and modern."</p>
          <div class="t-author">Ahmed N.<span>Member since 2023</span></div>
        </div>"""

    testimonials_new = """        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Going solar with {{ lead.name }} was the best investment we've made. The installation was smooth, clean, and our monthly electric bill went from $250 to just $12!"</p>
          <div class="t-author">Sarah M.<span>Homeowner</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"The team at {{ lead.name }} was incredibly detailed. They handled all the HOA approvals, utility hookups, and the battery storage has been flawless during outages."</p>
          <div class="t-author">James K.<span>Austin Resident</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"I had quotes from three different solar companies, but {{ lead.name }} was by far the most transparent. No pressure tactics, just honest math and top-tier equipment."</p>
          <div class="t-author">Priya R.<span>Property Owner</span></div>
        </div>
        <div class="t-card">
          <div class="t-stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div>
          <p>"Highly recommend {{ lead.name }}. Very quick installation, great financing options, and the real-time energy monitoring app is super satisfying to watch."</p>
          <div class="t-author">Ahmed N.<span>Homeowner</span></div>
        </div>"""
    html = html.replace(testimonials_old, testimonials_new)
    
    html = html.replace('<span class="section-tag">What Members Say</span>', '<span class="section-tag">What Property Owners Say</span>')
    html = html.replace('Real Stories, Real Results', 'Recent Customer Reviews')

    # Remove dynamic preview customizer script since Jinja handles rendering
    html = re.sub(r'<!-- DYNAMIC PREVIEW CUSTOMIZATION SCRIPT -->.*?<!-- TRACKING SCRIPT -->', '<!-- TRACKING SCRIPT -->', html, flags=re.DOTALL)
    
    # 9. Update tracking beacons
    html = html.replace('bid="122"', 'bid="{{ lead.id }}"')
    html = html.replace('bid=122', 'bid={{ lead.id }}')
    html = html.replace('BID="122"', 'BID="{{ lead.id }}"')
    html = html.replace('https://lived-britney-herself-calendar.trycloudflare.com', '{{ tracking_beacon_url or "" }}')
    
    # 10. Update footer credit
    html = html.replace('contact@raincityfit.com', '{{ lead.email or \'info@\' + lead.website }}')
    html = html.replace('Based on http://www.aliofitnessclubs.com', '')

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("Solar template converted.")

if __name__ == "__main__":
    convert_roofer()
    convert_hvac()
    convert_solar()
