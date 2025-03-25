import scrapy
import json
from target_scraper.items import TargetItem
try:
    from scrapy_splash import SplashRequest
except ImportError:
    SplashRequest = None  # Fallback if Splash isn’t installed

class TargetSpider(scrapy.Spider):
    name = 'target'
    allowed_domains = ['target.com']

    def __init__(self, url=None, *args, **kwargs):
        super(TargetSpider, self).__init__(*args, **kwargs)
        if url:
            self.start_urls = [url]
        else:
            raise ValueError('Please provide a URL using -a url=...')
        # Check if Splash is available
        self.use_splash = SplashRequest is not None
        if not self.use_splash:
            self.logger.warning("Scrapy-Splash not installed. Falling back to static HTML parsing, which may miss JS-rendered content.")

    def start_requests(self):
        for url in self.start_urls:
            if self.use_splash:
                # Use Splash to render JavaScript with a longer wait time
                yield SplashRequest(url, self.parse, args={'wait': 10}, endpoint='render.html')
            else:
                # Fallback to regular Scrapy request
                yield scrapy.Request(url, self.parse)

    def parse(self, response):
        item = TargetItem()

        # Log the full raw response for debugging (up to 5000 chars)
        self.logger.debug(f"Raw HTML response: {response.text[:5000]}...")

        # Extract TCIN from URL
        tcin = response.url.split('/-/A-')[-1].split('#')[0]
        item['tcin_id'] = tcin

        # Try JSON parsing first
        script_data = response.xpath('//script[contains(text(), "window.__INITIAL_STATE__")]/text()').get()
        if script_data:
            try:
                json_data = script_data.split('window.__INITIAL_STATE__ = ')[1].strip().rstrip(';')
                data = json.loads(json_data)
                product_data = data.get('product', {}).get('details', {})
                price_data = data.get('product', {}).get('price', {})
                item['product_name'] = product_data.get('title')
                item['categories'] = product_data.get('categories', [])
                item['model_no'] = product_data.get('modelNumber')
                item['images'] = product_data.get('images', [])
                item['specifications'] = product_data.get('specifications', [])
                item['description'] = product_data.get('description', '')
                item['variant'] = product_data.get('variant', '')
                # Explicitly check multiple price fields
                item['price'] = price_data.get('current_retail') or price_data.get('formatted_current_price') or price_data.get('price')
                item['discount_price'] = price_data.get('current_retail_min') if price_data.get('current_retail_min') != price_data.get('current_retail') else None
                item['sellers'] = ['Target']
                self.logger.info(f"JSON price data: {price_data}")
                self.logger.info("Data extracted from JSON")
            except (json.JSONDecodeError, IndexError):
                self.logger.warning("JSON parsing failed, using fallback")
                self._parse_fallback(response, item)
        else:
            self.logger.info("No JSON data found, using fallback")
            self._parse_fallback(response, item)

        self.logger.info(f"Final extracted item: {dict(item)}")
        yield item

    def _parse_fallback(self, response, item):
        # Product name
        item['product_name'] = response.xpath('//h1[contains(@class, "Heading")]/text()').get()

        # Categories
        categories = response.xpath('//nav[@aria-label="Breadcrumbs"]//a[@data-test="@web/Breadcrumbs/BreadcrumbLink"]/text()').getall()
        item['categories'] = [cat.strip() for cat in categories if cat.strip()] if categories else []

        # Model number
        item['model_no'] = response.url.split('/-/A-')[-1].split('#')[0]

        # Images
        # Extract the image URL from the src attribute
        item['images'] = response.xpath('//div[contains(@class, "styles_zoomableImage__R_OOf")]//img/@src').getall()

        # Specifications extraction
        # Now extracting from the updated structure:
        specs_xpath = '//div[@data-test="item-details-specifications"]//div/div/div[1]/b/text()'
        specs_values_xpath = '//div[@data-test="item-details-specifications"]//div/div/div[1]/text()'

        specs = response.xpath(specs_xpath).getall()
        specs_values = response.xpath(specs_values_xpath).getall()

        # Combine the specifications and their values into a dictionary
        specifications = {spec.strip(): value.strip() for spec, value in zip(specs, specs_values)}

        # If no specifications are found, use a fallback search
        if not specifications:
            self.logger.warning("No specifications found with primary XPath. Attempting fallback...")
            fallback_specs_xpath = '//div[@data-test="item-details-specifications"]//div//text()'
            specifications = {spec.strip(): "" for spec in response.xpath(fallback_specs_xpath).getall()}

        item['specifications'] = specifications
        self.logger.info(f"Final specifications: {item['specifications']}")

        # Description extraction
        description = response.xpath('//div[contains(@class, "h-margin-t-x2") and @data-test="item-details-description"]//text()').getall()
        if not description or not any(d.strip() for d in description):
            description = response.xpath('//h4[contains(@class, "styles_ndsHeading__HcGpD") and contains(text(), "Description")]/following-sibling::div//div[contains(@class, "h-margin-t-x2")]//text()').getall()
        if not description or not any(d.strip() for d in description):
            description = description = response.xpath('//meta[@name="description"]/@content').get()
        item['description'] = description if description else ''

        # Price extraction with extensive fallbacks and detailed logging
        # Primary attempt: simple extraction by data-test attribute
        price = response.xpath('//span[@data-test="product-price"]/text()').get()
        self.logger.debug(f"Price attempt 1 (data-test product-price): {price}")
        if not price:
            price = response.xpath('//span[contains(@class, "sc-4d225cde-1")]/text()').get()
            self.logger.debug(f"Price attempt 2 (class sc-4d225cde-1): {price}")
        if not price:
            price = response.xpath('//span[@data-test="product-price"]//text()').get()
            self.logger.debug(f"Price attempt 3 (nested product-price): {price}")
        if not price:
            price = response.xpath('//div[contains(@class, "price")]//span/text()').get()
            self.logger.debug(f"Price attempt 4 (generic price class): {price}")
        if not price:
            price = response.xpath('//span[contains(text(), "$")]/text()').get()  # Broad search for any $-containing span
            self.logger.debug(f"Price attempt 5 (any $): {price}")
        item['price'] = price.strip() if price else None
        self.logger.debug(f"Final extracted price: {item['price']}")

        # Discount price
        discount_price = response.xpath('//span[@data-test="sale-price"]/text()').get() or \
                         response.xpath('//span[contains(@class, "sale-price")]/text()').get()
        item['discount_price'] = discount_price.strip() if discount_price else None

        # Sellers
        item['sellers'] = ['Target']

        self.logger.info(f"Final extracted item: {dict(item)}")




# import scrapy

# class TargetSpider(scrapy.Spider):
#     name = "target"
#     allowed_domains = ["target.com"]

#     def start_requests(self):
#         urls = [
#             "https://www.target.com/p/hp-inc-essential-laptop-computer-17-3-hd-intel-core-8-gb-memory-256-gb-ssd/-/A-92469343#lnk=sametab"
#         ]
#         for url in urls:
#             yield scrapy.Request(url=url, callback=self.parse)

#     def parse(self, response):
#         # Extract product name from the og:title meta tag
#         product_name = response.xpath('//meta[@property="og:title"]/@content').get()

#         # Extract description from meta description
#         description = response.xpath('//meta[@name="description"]/@content').get()

#         # Get the canonical URL and extract the product id (Model no & Tcin id)
#         canonical = response.xpath('//link[@rel="canonical"]/@href').get()
#         product_id = None
#         if canonical:
#             # Example canonical: https://www.target.com/p/hp-inc-essential-laptop-computer-17-3-hd-intel-core-8-gb-memory-256-gb-ssd/-/A-92469343
#             parts = canonical.rstrip('/').split('/')
#             if parts:
#                 product_id = parts[-1]  # e.g., A-92469343

#         # Extract image URL from meta og:image
#         image = response.xpath('//meta[@property="og:image"]/@content').get()
#         images = [image] if image else []

#         # The following details are not available in the given HTML sample.
#         # You might need additional parsing or an API request to get these details.
#         categories = []         # Not provided in meta tags
#         specifications = []     # Not provided
#         variant = []            # Not provided
#         price = None            # Not provided
#         discount_price = None   # Not provided
#         sellers = None          # Not provided

#         # Build the item with all the required fields
#         item = {
#             'Product Name': product_name,
#             'Categories': categories,
#             'Model No': product_id,
#             'Tcin ID': product_id,
#             'Images': images,
#             'Specifications': specifications,
#             'Description': description,
#             'Variant': variant,
#             'Price': price,
#             'Discount Price': discount_price,
#             'Sellers': sellers,
#         }

#         # Yield the item so that Scrapy outputs it (e.g., with -o output.json)
#         yield item
