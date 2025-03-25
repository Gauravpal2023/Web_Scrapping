# target_scraper/items.py
import scrapy

class TargetItem(scrapy.Item):
    product_name = scrapy.Field()
    categories = scrapy.Field()
    model_no = scrapy.Field()
    tcin_id = scrapy.Field()
    images = scrapy.Field()
    specifications = scrapy.Field()
    description = scrapy.Field()
    variant = scrapy.Field()
    price = scrapy.Field()
    discount_price = scrapy.Field()
    sellers = scrapy.Field()