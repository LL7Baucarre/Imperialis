"""GDM mission scraper package for Imperialis.

Scrapes https://gdmissions.app (alias game-datamissions.com/11th) for
11th-edition Warhammer 40,000 mission data using only the Python stdlib.
"""
from .gdm_scraper import scrape

__all__ = ["scrape"]