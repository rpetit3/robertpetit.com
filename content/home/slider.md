+++
# Slider widget.
widget = "slider"  # See https://sourcethemes.com/academic/docs/page-builder/
headless = true  # This file represents a page section.
active = false  # Activate this widget? true/false
weight = 20  # Order that this section will appear.

# Slide interval.
# Use `false` to disable animation or enter a time in ms, e.g. `5000` (5s).
interval = false

# Slide height (optional).
# E.g. `500px` for 500 pixels or `calc(100vh - 70px)` for full screen.
height = "325px"

# Slides.
# Duplicate an `[[item]]` block to add more slides.
[[item]]
  title = "Workshop Feedback"
  content = "\"Alison was knowledgeable but at the same time very approachable. She had a sense of humor and very engaging style that gave me confidence that I can do this.\""
  align = "center"  # Choose `center`, `left`, or `right`.

  # Overlay a color or image (optional).
  #   Deactivate an option by commenting out the line, prefixing it with `#`.
  overlay_color = "#404040"  # An HTML color value.
  overlay_img = "headers/supplies.jpg"  # Image path relative to your `static/img/` folder.
  overlay_filter = 0.1  # Darken the image. Value in range 0-1.

  # Call to action button (optional).
  #   Activate the button by specifying a URL and button label below.
  #   Deactivate by commenting out parameters, prefixing lines with `#`.
  cta_label = "see my workshops"
  cta_url = "categories/workshop/"
  cta_icon_pack = "fas"
  cta_icon = "binoculars"

[[item]]
  title = "Workshop Feedback"
  content = "\"Alison is a phenomenal teacher, and her enthusiasm for the subject matter is palpable.\""
  align = "left"

  overlay_color = "#404040"  # An HTML color value.
  overlay_img = "headers/supplies-yellow.jpg"  # Image path relative to your `static/img/` folder.
  overlay_filter = 0.1  # Darken the image. Value in range 0-1.
  
  cta_label = "see my workshops"
  cta_url = "categories/workshop/"
  cta_icon_pack = "fas"
  cta_icon = "binoculars"
+++
