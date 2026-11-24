# How Dionysios works with AI agents

## Claude inside WordPress over MCP
Each of his nine live client sites runs Novamira, a WordPress plugin that exposes the site as an MCP server through the WordPress MCP Adapter and Abilities API. Claude connects to it and can run PHP, read and write files, use WP-CLI and work with the database of the live site. A client request ("add a payment receipt", "the schedule must show only next week") becomes a conversation with the agent, which writes the code inside the site; Dionysios reads it, tests it on the site and fixes what is wrong.

## Guardrails he uses on live sites
- Generated PHP goes into a sandbox folder (wp-content/novamira-sandbox). A broken file can be disabled on its own without taking the site down.
- Before risky edits he keeps dated backup copies of the files being changed.
- Data is modelled the WordPress-native way: custom post types, custom roles and capabilities, custom REST endpoints, instead of hard-coded content.
- Access is role-based: in the Apollon members area a parent sees only their own children; coaches, the office and the board each see only their part.

## Example of scale
On the Apollon Chalandriou site the members area is built from about 75 custom PHP modules written with Claude over MCP: attendance, fees and receipts, evaluations, coach panel, privacy and access control, data import and export.

## LLM APIs inside the software he builds
On Pame Theatro (pame.gowebgo.gr) an editor uploads a theatre press release and the Claude Messages API returns the show's fields as JSON in a fixed schema (structured output). The model is told to leave anything it cannot find empty instead of guessing, and to add notes about what needs checking. Nothing is saved automatically: a person reviews the form and saves it. The API key lives in wp-config.php or an admin-only setting and is only shown masked.

## His own tools
- goWebgo SEO: his own lightweight SEO plugin, installed across his sites. It handles titles, descriptions, social sharing, schema, sitemap, redirects and 404s, multiple keywords and bulk page checks. It reads and writes SEOPress fields and reads Yoast fields, so a site can switch without migrating data.
- Custom "core" plugins per site (for example Brecht Core, ZerdelisBox Core, Golden Times Core, Xoros 2510 Core) that hold the site's custom logic, separate from the theme.

## Hosting setup
His sites run on Hostinger with LiteSpeed cache, recent WordPress versions and PHP 8.x. Several use Koko Analytics, a privacy-friendly analytics plugin, instead of tracking cookies.

## Turning a vague request into a demo
He starts from what the client actually does every day, builds the smallest working version inside their site, shows it to them on their phone, and iterates until it does what they need.
