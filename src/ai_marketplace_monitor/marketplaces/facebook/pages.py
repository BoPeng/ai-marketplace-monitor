"""Facebook pages: search results, listings, the location dialog and seller profiles."""

import datetime
import re
from dataclasses import asdict
from logging import Logger
from typing import TYPE_CHECKING, Any, List, Tuple, cast

from rich.pretty import pretty_repr

from ...evaluations import (
    AVAILABLE,
    PENDING,
    SOLD,
)
from ...listing import Listing
from ...seller import (
    Seller,
)
from ...utils import (
    Translator,
    extract_price,
    hilight,
)
from ..base import (
    WebPage,
)

if TYPE_CHECKING:
    from playwright.sync_api import (  # type: ignore
        ElementHandle,
        Page,
    )


from .seller import (
    parse_seller_panel,
    parse_seller_profile,
    seller_id_from_url,
    sold_grid_count,
)


def listing_state(title: str, translator: Translator | None = None) -> Tuple[str, str]:
    """The state a listing page's title shows, and the title without it.

    Facebook puts "Sold" or "Pending" before the title of such a listing:
    ``"Sold · 2018 Honda accord"``.
    """
    t = translator or Translator()
    for state, label in ((SOLD, t("Sold")), (PENDING, t("Pending"))):
        matched = re.match(rf"\s*{re.escape(label)}[\s\xa0]*·\s*(.*)$", title, re.DOTALL)
        if matched:
            return state, matched.group(1).strip()
    return AVAILABLE, title


_FACEBOOK_INLINE_STYLE_RE = re.compile(r"\.[A-Za-z0-9_-]+\{[^{}]*inline-size:[^{}]*\}")
_FACEBOOK_AD_BLOCK_RE = re.compile(
    r"(?:^|\s)Ads\s*" + _FACEBOOK_INLINE_STYLE_RE.pattern + r".*$",
    re.IGNORECASE | re.DOTALL,
)


# the radii Facebook's location dialog offers, in the unit it shows (miles in the US)
RADIUS_CHOICES = (1, 2, 5, 10, 20, 40, 60, 80, 100, 250, 500)


def radius_from_label(label: str) -> int | None:
    """The radius in "Location: Houston, Texas, Within 40 mi" (or "Radius 40 miles")."""
    numbers = re.findall(r"(\d+)\s*[^\d\s,]+\s*$", label.strip())
    return int(numbers[-1]) if numbers else None


def nearest_radius(radius: float, choices: "Tuple[int, ...] | List[int]" = RADIUS_CHOICES) -> int:
    """The choice closest to ``radius``; the larger one on a tie."""
    return min(choices, key=lambda c: (abs(c - radius), -c))


def _clean_facebook_description(text: str) -> str:
    """Remove Facebook-injected ad/video text from listing descriptions."""
    text = text.replace("\xa0", " ").strip()
    text = _FACEBOOK_AD_BLOCK_RE.sub("", text)
    text = _FACEBOOK_INLINE_STYLE_RE.sub(" ", text)
    text = text.replace("Sorry, we're having trouble playing this video.", " ")
    text = text.replace("Learn more", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class FacebookSearchResultPage(WebPage):
    def _get_listings_elements_by_children_counts(self: "FacebookSearchResultPage"):
        parent: ElementHandle | None = self.page.locator("img").first.element_handle()
        # look for parent of parent until it has more than 10 children
        children = []
        while parent:
            children = parent.query_selector_all(":scope > *")
            if len(children) > 10:
                break
            parent = parent.query_selector("xpath=..")
        # find each listing
        valid_listings = []
        try:
            for listing in children:
                if not listing.text_content():
                    continue
                valid_listings.append(listing)
        except Exception as e:
            # this error should be tolerated
            if self.logger:
                self.logger.debug(
                    f"{hilight('[Retrieve]', 'fail')} Some grid item cannot be read: {e}"
                )
        return valid_listings

    def _get_listing_elements_by_traversing_header(self: "FacebookSearchResultPage"):
        heading = self.page.locator(
            f'[aria-label="{self.translator("Collection of Marketplace items")}"]'
        )
        if not heading:
            return []

        grid_items = heading.locator(
            ":scope > :first-child > :first-child > :nth-child(3) > :first-child > :nth-child(2) > div"
        )
        # find each listing
        valid_listings = []
        try:
            for listing in grid_items.all():
                if not listing.text_content():
                    continue
                valid_listings.append(listing.element_handle())
        except Exception as e:
            # this error should be tolerated
            if self.logger:
                self.logger.debug(
                    f"{hilight('[Retrieve]', 'fail')} Some grid item cannot be read: {e}"
                )
        return valid_listings

    def get_listings(self: "FacebookSearchResultPage") -> List[Listing]:
        # if no result is found
        btn = self.page.locator(f"""span:has-text('{self.translator("Browse Marketplace")}')""")
        if btn.count() > 0:
            if self.logger:
                msg = self._parent_with_cond(
                    btn.first,
                    lambda x: len(x) == 3
                    and self.translator("Browse Marketplace") in (x[-1].text_content() or ""),
                    1,
                )
                self.logger.info(f"{hilight('[Retrieve]', 'dim')} {msg}")
            return []

        # find the grid box
        try:
            valid_listings = (
                self._get_listing_elements_by_traversing_header()
                or self._get_listings_elements_by_children_counts()
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            filename = datetime.datetime.now().strftime("debug_%Y%m%d_%H%M%S.html")
            if self.logger:
                self.logger.error(
                    f"{hilight('[Retrieve]', 'fail')} failed to parse searching result. Page saved to {filename}: {e}"
                )
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.page.content())
            return []

        listings: List[Listing] = []
        for idx, listing in enumerate(valid_listings):
            try:
                atag = listing.query_selector(
                    ":scope > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child"
                )
                if not atag:
                    continue
                post_url = atag.get_attribute("href") or ""
                details_divs = atag.query_selector_all(":scope > :first-child > div")
                if not details_divs:
                    continue
                details = details_divs[1]
                divs = details.query_selector_all(":scope > div")
                raw_price = "" if len(divs) < 1 else divs[0].text_content() or ""
                title = "" if len(divs) < 2 else divs[1].text_content() or ""
                # location can be empty in some rare cases
                location = "" if len(divs) < 3 else (divs[2].text_content() or "")

                # get image
                img = listing.query_selector("img")
                image = img.get_attribute("src") if img else ""
                price = extract_price(raw_price)

                if post_url.startswith("/"):
                    post_url = f"https://www.facebook.com{post_url}"

                if image.startswith("/"):
                    image = f"https://www.facebook.com{image}"

                listings.append(
                    Listing(
                        marketplace="facebook",
                        name="",
                        id=post_url.split("?")[0].rstrip("/").split("/")[-1],
                        title=title,
                        image=image,
                        price=price,
                        # all the ?referral_code&referral_sotry_type etc
                        # could be helpful for live navigation, but will be stripped
                        # for caching item details.
                        post_url=post_url,
                        location=location,
                        condition="",
                        seller="",
                        description="",
                    )
                )
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.error(
                        f"{hilight('[Retrieve]', 'fail')} Failed to parse search results {idx + 1} listing: {e}"
                    )
                continue
        return listings


_SELLER_PANEL_JS = """// the seller panel: the smallest element around one of the seller's links that also
// says when they joined
(joined) => {
    const links = [...document.querySelectorAll('a[href*="/marketplace/profile/"]')];
    if (!links.length) return null;
    let best = null, bestDepth = 99;
    for (const link of links) {
        let node = link;
        for (let depth = 0; depth < 25 && node; depth++, node = node.parentElement) {
            if ((node.innerText || "").includes(joined)) {
                if (depth < bestDepth) { best = node; bestDepth = depth; }
                break;
            }
        }
    }
    const scope = best || links[links.length - 1].parentElement;
    return {
        href: links[0].getAttribute("href") || "",
        text: scope ? scope.innerText : "",
        labels: scope ? [...scope.querySelectorAll("[aria-label]")].map(e => e.getAttribute("aria-label")) : [],
    };
}"""


class FacebookLocationDialog(WebPage):
    """Marketplace's location dialog ("Change location"): a place and a radius.

    Facebook searches with the place and radius saved on the account, which only this dialog
    changes; the place in a search URL wins, but the radius there is ignored.
    """

    def _button(self: "FacebookLocationDialog") -> Any:
        return self.page.locator(f'[aria-label^="{self.translator("Location:")}"]').first

    def _dialog(self: "FacebookLocationDialog") -> Any:
        return self.page.get_by_role("dialog", name=self.translator("Change location"))

    def current_label(self: "FacebookLocationDialog") -> str:
        """The location button: "Location: Houston, Texas, Within 40 mi"."""
        return str(self._button().get_attribute("aria-label", timeout=10000) or "")

    def current_radius(self: "FacebookLocationDialog") -> int | None:
        return radius_from_label(self.current_label())

    def open(self: "FacebookLocationDialog") -> None:
        self._button().click(timeout=5000)
        self._dialog().wait_for(timeout=10000)

    def close(self: "FacebookLocationDialog") -> None:
        """Close the dialog (and a list open in it) without applying."""
        try:
            for _ in range(2):
                self.page.keyboard.press("Escape")
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: S110
            pass

    def _radius_field(self: "FacebookLocationDialog") -> Any:
        return self._dialog().get_by_role("combobox").filter(has_text=self.translator("Radius"))

    def choose_radius(self: "FacebookLocationDialog", radius: float) -> str:
        """Choose the radius nearest ``radius``; its text, e.g. "40 miles"."""
        self._radius_field().click(timeout=5000)
        options = self.page.get_by_role("option")
        options.first.wait_for(timeout=5000)
        choices = {}
        for text in options.all_inner_texts():
            value = radius_from_label(text)
            if value is not None:
                choices[value] = text.strip()
        if not choices:
            raise ValueError("the location dialog offers no radius")
        chosen = choices[nearest_radius(radius, sorted(choices))]
        self.page.get_by_role("option", name=chosen, exact=True).click(timeout=5000)
        return chosen

    def apply(self: "FacebookLocationDialog") -> None:
        """Apply the dialog; the page reloads with the place and radius."""
        self._dialog().get_by_role("button", name=self.translator("Apply"), exact=True).click(
            timeout=5000
        )
        self.page.wait_for_timeout(3000)


class FacebookItemPage(WebPage):
    def verify_layout(self: "FacebookItemPage") -> bool:
        return True

    def get_title(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_title is not implemented for this page")

    def get_price(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_price is not implemented for this page")

    def get_image_url(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_image_url is not implemented for this page")

    def get_seller(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_seller is not implemented for this page")

    def get_description(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_description is not implemented for this page")

    def get_location(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_location is not implemented for this page")

    def get_condition(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_condition is not implemented for this page")

    def get_seller_info(self: "FacebookItemPage", name: str = "") -> Seller | None:
        """The seller as the page's "Seller information" panel shows them, if it does."""
        try:
            panel = self.page.evaluate(_SELLER_PANEL_JS, self.translator("Joined Facebook in"))
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} seller panel: {e}")
            return None
        if not panel:
            return None
        seller_id = seller_id_from_url(panel.get("href", ""))
        if not seller_id:
            return None
        return parse_seller_panel(
            panel.get("text") or "",
            [x for x in panel.get("labels") or [] if x],
            seller_id,
            name=name,
            translator=self.translator,
        )

    def _expand_see_more(self: "FacebookItemPage") -> None:
        """Click any 'See more' disclosure links to expand truncated descriptions."""
        try:
            see_more_buttons = self.page.locator(
                f'div[role="button"]:has(span:text("{self.translator("See more")}"))'
            )
            # wait briefly for "See more" buttons to appear in the DOM
            see_more_buttons.first.wait_for(state="visible", timeout=8000)
            for i in range(see_more_buttons.count()):
                see_more_buttons.nth(i).click(timeout=2000)
            # allow the DOM to update after clicking
            self.page.wait_for_timeout(500)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} See more expansion: {e}")

    def parse(self: "FacebookItemPage", post_url: str) -> Listing:
        if not self.verify_layout():
            raise ValueError("Layout mismatch")

        # expand any truncated description sections before extracting text
        self._expand_see_more()

        # title
        title = self.get_title()
        price = self.get_price()
        description = _clean_facebook_description(self.get_description())
        # strip disclosure button text left over after expanding "See more"
        for label in (self.translator("See more"), self.translator("See less")):
            description = description.replace(label, "").strip()

        if not title or not price:
            raise ValueError(f"Failed to parse {post_url}")

        if self.logger:
            self.logger.info(f"{hilight('[Retrieve]', 'succ')} Parsing {hilight(title)}")
        res = Listing(
            marketplace="facebook",
            name="",
            id=post_url.split("?")[0].rstrip("/").split("/")[-1],
            title=title,
            image=self.get_image_url(),
            price=extract_price(price),
            post_url=post_url,
            location=self.get_location(),
            condition=self.get_condition(),
            description=description,
            seller=self.get_seller(),
        )
        res.seller_parsed = True
        seller = self.get_seller_info(res.seller)
        if seller is not None:
            res.seller_id = seller.id
            res.seller_info = {"seller": asdict(seller)}
        if self.logger:
            self.logger.debug(f"{hilight('[Retrieve]', 'succ')} {pretty_repr(res)}")
        return cast(Listing, res)


class FacebookRegularItemPage(FacebookItemPage):
    def verify_layout(self: "FacebookRegularItemPage") -> bool:
        return any(
            self.translator("Condition") in (x.text_content() or "")
            for x in self.page.query_selector_all("li")
        )

    def get_title(self: "FacebookRegularItemPage") -> str:
        try:
            h1_element = self.page.query_selector_all("h1")[-1]
            return h1_element.text_content() or self.translator("**unspecified**")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_price(self: "FacebookRegularItemPage") -> str:
        try:
            price_element = self.page.locator("h1 + *")
            return price_element.text_content() or self.translator("**unspecified**")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_image_url(self: "FacebookRegularItemPage") -> str:
        try:
            image_url = self.page.locator("img").first.get_attribute("src") or ""
            return image_url
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_seller(self: "FacebookRegularItemPage") -> str:
        try:
            seller_locator = self.page.locator("//a[contains(@href, '/marketplace/profile')]")
            if seller_locator.count() == 0:
                # Try an alternative pattern — Facebook sometimes uses
                # different link structures for the seller name.
                seller_locator = self.page.locator("//a[contains(@href, '/profile')]")
            if seller_locator.count() == 0:
                return self.translator("**unspecified**")
            # Use a short timeout to avoid a 30s delay when seller data is not
            # present (e.g. in anonymous/not-logged-in mode). See #289.
            return seller_locator.last.text_content(timeout=3000) or self.translator(
                "**unspecified**"
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(
                    f"{hilight('[Retrieve]', 'fail')} get_seller failed: {type(e).__name__}: {e}"
                )
            return self.translator("**unspecified**")

    def get_description(self: "FacebookRegularItemPage") -> str:
        try:
            # Find the span with text "condition", then parent, then next...
            description_element = self.page.locator(
                f'span:text("{self.translator("Condition")}") >> xpath=ancestor::ul[1] >> xpath=following-sibling::*[1]'
            )
            return description_element.text_content() or self.translator("**unspecified**")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_condition(self: "FacebookRegularItemPage") -> str:
        try:
            if self.logger:
                self.logger.debug(f"{hilight('[Debug]', 'info')} Getting condition info...")
            # Find the span with text "condition", then parent, then next...
            condition_text = self.translator("Condition")

            # Use .first property to avoid strict mode violation when multiple elements match
            # This handles cases where "Condition" appears in both the label and description text
            condition_locator = self.page.locator(f'span:text("{condition_text}")')
            condition_element = condition_locator.first

            result = self._parent_with_cond(
                condition_element,
                lambda x: len(x) >= 2
                and self.translator("Condition") in (x[0].text_content() or ""),
                1,
            )
            return result
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"{hilight('[Error]', 'fail')} get_condition failed: {type(e).__name__}: {e}"
                )
            return ""

    def get_location(self: "FacebookRegularItemPage") -> str:
        try:
            # look for "Location is approximate", then find its neighbor
            approximate_element = self.page.locator(
                f'span:text("{self.translator("Location is approximate")}")'
            )
            return self._parent_with_cond(
                approximate_element,
                lambda x: len(x) == 2
                and self.translator("Location is approximate") in (x[1].text_content() or ""),
                0,
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""


class FacebookFlexItemPage(FacebookRegularItemPage):
    """Layout observed since mid-2026.

    The Details section renders Condition, condition value, and description in
    nested span/div structures instead of the previous ul/li lists. See #326.
    """

    def verify_layout(self: "FacebookFlexItemPage") -> bool:
        return (
            self.page.locator(f'span:text-is("{self.translator("Condition")}")').count() > 0
            and len(self.page.query_selector_all("h1")) > 0
        )

    def _condition_and_description(self: "FacebookFlexItemPage") -> List[str]:
        """Extract the condition value and description from the Details section.

        Climb from the Condition label; the first non-empty next-sibling text
        is the condition value, the second is the description. Some categories
        list more attributes after Condition (e.g. "Has Bluetooth: Yes"), in rows
        built like the Condition row; such siblings are skipped, so the
        description is the text that follows the block of attribute rows.
        """
        label = self.page.query_selector(f'span:text-is("{self.translator("Condition")}")')
        if label is None:
            return []
        return label.evaluate(
            """(el) => {
              const shape = (e) => e.tagName + '(' + [...e.children].map(shape).join(',') + ')';
              const hits = [];
              let n = el;
              for (let i = 0; i < 16 && n && hits.length < 2; i++) {
                let sib = n.nextElementSibling;
                if (hits.length) {
                  // after the condition: skip more attribute rows built like this one
                  const row = shape(n);
                  while (sib && shape(sib) === row) sib = sib.nextElementSibling;
                }
                const t = sib && sib.textContent ? sib.textContent.trim() : '';
                if (t) hits.push(t);
                n = n.parentElement;
              }
              return hits;
            }"""
        )

    def get_condition(self: "FacebookFlexItemPage") -> str:
        try:
            hits = self._condition_and_description()
            return hits[0] if hits else ""
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_description(self: "FacebookFlexItemPage") -> str:
        try:
            hits = self._condition_and_description()
            return hits[1] if len(hits) > 1 else ""
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_location(self: "FacebookFlexItemPage") -> str:
        try:
            phrase = self.translator("Location is approximate")
            label = self.page.query_selector(f'span:text("{phrase}")')
            if label is None:
                return ""
            text = label.evaluate(
                """(el, phrase) => {
                  let n = el;
                  for (let i = 0; i < 10 && n; i++) {
                    const t = (n.textContent || '').trim();
                    if (t.split(phrase).join('').split('\\u00b7').join('').trim()) return t;
                    n = n.parentElement;
                  }
                  return '';
                }""",
                phrase,
            )
            return text.replace(phrase, "").replace("·", "").strip()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""


class FacebookRentalItemPage(FacebookRegularItemPage):
    def verify_layout(self: "FacebookRentalItemPage") -> bool:
        # there is a header h2 with text Description
        return any(
            self.translator("Description") in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def get_description(self: "FacebookRentalItemPage") -> str:
        # some pages do not have a condition box and appears to have a "Description" header
        # See https://github.com/BoPeng/ai-marketplace-monitor/issues/29 for details.
        try:
            description_header = self.page.query_selector(
                f'h2:has(span:text("{self.translator("Description")}"))'
            )
            return self._parent_with_cond(
                description_header,
                lambda x: len(x) > 1 and x[0].text_content() == self.translator("Description"),
                1,
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_condition(self: "FacebookRentalItemPage") -> str:
        # no condition information for rental items
        return self.translator("**unspecified**")


_VEHICLE_EMOJI_PATTERNS = [
    ("Driven", "🚗"),
    ("transmission", "⚙️"),
    ("color", "🎨"),
    ("safety rating", "⭐"),
    ("NHTSA", "⭐"),
    ("Fuel type", "⛽"),
    ("MPG", "⛽"),
    ("owner", "👤"),
    ("paid off", "💰"),
    ("Clean title", "✅"),
    ("no significant damage", "✅"),
    ("Salvage", "⚠️"),
    ("accident", "⚠️"),
]


def _add_vehicle_emojis(text: str) -> str:
    """Prepend emoji indicators to known vehicle attribute lines."""
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        emoji = ""
        for pattern, icon in _VEHICLE_EMOJI_PATTERNS:
            if pattern.lower() in stripped.lower():
                emoji = icon + " "
                break
        result.append(emoji + stripped)
    return "\n".join(result)


class FacebookAutoItemWithAboutAndDescriptionPage(FacebookRegularItemPage):
    def _has_about_this_vehicle(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> bool:
        return any(
            self.translator("About this vehicle") in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def _has_seller_description(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> bool:
        return any(
            self.translator("Seller's description") in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def _get_about_this_vehicle(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        try:
            about_element = self.page.locator(
                f'h2:has(span:text("{self.translator("About this vehicle")}"))'
            )
            return self._parent_with_cond(
                # start from About this vehicle
                about_element,
                # find an array of elements with the first one being "About this vehicle"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("About this vehicle") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # Extract all texts, using inner_text to preserve line breaks, and add emojis
                lambda x: _add_vehicle_emojis(
                    "\n".join([child.inner_text() or "" for child in x])
                ),
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def _get_seller_description(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        try:
            description_header = self.page.query_selector(
                f"""h2:has(span:text("{self.translator("Seller's description")}"))"""
            )

            return self._parent_with_cond(
                # start from the description header
                description_header,
                # find an array of elements with the first one being "Seller's description"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("Seller's description") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # then, drill down from the second child
                lambda x: self._children_with_cond(
                    x[1],
                    # find the an array of elements
                    lambda y: len(y) > 1,
                    # and return the texts.
                    lambda y: f"""\n\n{self.translator("Seller's description")}\n\n{y[0].text_content() or self.translator("**unspecified**")}""",
                ),
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def verify_layout(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> bool:
        # there is a header h2 with text "About this vehicle"
        return self._has_about_this_vehicle() and self._has_seller_description()

    def get_description(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        return self._get_about_this_vehicle() + self._get_seller_description()

    def get_price(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        description = self.get_description()
        # using regular expression to find text that looks like price in the description
        price_pattern = r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:,\d{2})?"
        match = re.search(price_pattern, description)
        return match.group(0) if match else self.translator("**unspecified**")

    def get_condition(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        # no condition information for auto items
        return self.translator("**unspecified**")


class FacebookAutoItemWithDescriptionPage(FacebookAutoItemWithAboutAndDescriptionPage):
    def verify_layout(self: "FacebookAutoItemWithDescriptionPage") -> bool:
        return self._has_seller_description() and not self._has_about_this_vehicle()

    def get_description(self: "FacebookAutoItemWithDescriptionPage") -> str:
        try:
            description_header = self.page.query_selector(
                f"""h2:has(span:text("{self.translator("Seller's description")}"))"""
            )

            return self._parent_with_cond(
                # start from the description header
                description_header,
                # find an array of elements with the first one being "Seller's description"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("Seller's description") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # then, drill down from the second child
                lambda x: self._children_with_cond(
                    x[1],
                    # find the an array of elements
                    lambda y: len(y) > 2,
                    # and return the texts.
                    lambda y: f"""\n\n{self.translator("Seller's description")}\n\n{y[1].text_content() or self.translator("**unspecified**")}""",
                ),
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_condition(self: "FacebookAutoItemWithDescriptionPage") -> str:
        try:
            description_header = self.page.query_selector(
                f"""h2:has(span:text("{self.translator("Seller's description")}"))"""
            )

            res = self._parent_with_cond(
                # start from the description header
                description_header,
                # find an array of elements with the first one being "Seller's description"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("Seller's description") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # then, drill down from the second child
                lambda x: self._children_with_cond(
                    x[1],
                    # find the an array of elements
                    lambda y: len(y) > 2,
                    # and return the texts after seller's description.
                    lambda y: y[0].text_content() or self.translator("**unspecified**"),
                ),
            )
            if res.startswith(self.translator("Condition")):
                res = res[len(self.translator("Condition")) :]
            return res.strip()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_price(self: "FacebookAutoItemWithDescriptionPage") -> str:
        # for this page, price is after header
        try:
            h1_element = self.page.query_selector_all("h1")[-1]
            header = h1_element.text_content()
            return self._parent_with_cond(
                # start from the header
                h1_element,
                # find an array of elements with the first one being "Seller's description"
                lambda x: len(x) > 1 and header in (x[0].text_content() or ""),
                # then, find the element after header
                1,
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""


_SELLER_PROFILE_JS = """// the profile opens as a dialog over the Marketplace feed
(joined) => {
    const dialog = [...document.querySelectorAll('[role="dialog"]')].find(
        d => (d.innerText || "").includes(joined));
    if (!dialog) return null;
    return {
        text: dialog.innerText,
        labels: [...dialog.querySelectorAll("[aria-label]")].map(e => e.getAttribute("aria-label")),
    };
}"""


_SOLD_GRID_JS = """// the listings grid of the profile: its text, and the first line of each listing tile
(joined) => {
    const dialog = [...document.querySelectorAll('[role="dialog"]')].find(
        d => (d.innerText || "").includes(joined));
    if (!dialog) return null;
    const tiles = [...dialog.querySelectorAll("a[aria-label]")].filter(
        e => /listing \\d+\\s*$/.test(e.getAttribute("aria-label") || ""));
    return {
        text: dialog.innerText,
        tiles: tiles.map(e => ((e.innerText || "").trim().split("\\n")[0] || "").trim()),
    };
}"""


class FacebookSellerProfilePage(WebPage):
    """A seller's Marketplace profile, /marketplace/profile/<id>/."""

    def _read(self: "FacebookSellerProfilePage") -> dict | None:
        joined = self.translator("Joined Facebook in")
        for _ in range(10):
            content = self.page.evaluate(_SELLER_PROFILE_JS, joined)
            if content:
                return cast(dict, content)
            self.page.wait_for_timeout(1000)
        return None

    def get_sold_listings(self: "FacebookSellerProfilePage") -> int | None:
        """Switch the profile to its "Sold & out of stock" listings and count them.

        The grid keeps showing the active listings for a moment after the switch, so a count
        is accepted only once every tile carries the "Sold" badge (twice in a row), or the grid
        says "No listings found". Otherwise the number of sold listings stays unknown.
        """
        try:
            self.page.get_by_role(
                "combobox", name=self.translator("Inventory availability status")
            ).click(timeout=5000)
            self.page.get_by_text(self.translator("Sold & out of stock"), exact=True).last.click(
                timeout=5000
            )
            previous: int | None = None
            for _ in range(20):
                self.page.wait_for_timeout(500)
                grid = self.page.evaluate(_SOLD_GRID_JS, self.translator("Joined Facebook in"))
                if not grid:
                    continue
                count = sold_grid_count(
                    grid.get("text") or "", grid.get("tiles") or [], self.translator
                )
                if count == 0:
                    return 0
                if count is not None and count == previous:
                    return count
                previous = count
            return None
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} sold listings: {e}")
            return None

    def parse(self: "FacebookSellerProfilePage", seller_id: str) -> Seller:
        content = self._read()
        if content is None:
            raise ValueError(f"No seller profile found for {seller_id}")
        seller = parse_seller_profile(
            content.get("text") or "",
            [x for x in content.get("labels") or [] if x],
            seller_id,
            translator=self.translator,
        )
        if seller.active_listings:
            seller.sold_listings = self.get_sold_listings()
        if self.logger:
            self.logger.debug(f"{hilight('[Retrieve]', 'succ')} seller {pretty_repr(seller)}")
        return seller


def parse_listing(
    page: "Page", post_url: str, translator: Translator | None = None, logger: Logger | None = None
) -> Listing | None:
    supported_facebook_item_layouts = [
        FacebookRentalItemPage,
        FacebookAutoItemWithAboutAndDescriptionPage,
        FacebookAutoItemWithDescriptionPage,
        # the specific (ul/li) layout before the generic one: Flex also matches the older
        # pages, where it may pick up a wrong description; if Regular finds none, Flex is next
        FacebookRegularItemPage,
        FacebookFlexItemPage,
    ]

    # a layout that matches but fails to extract a description is kept only as a
    # fallback, so that a later layout that does extract the description is preferred
    fallback: Listing | None = None
    for page_model in supported_facebook_item_layouts:
        try:
            listing = page_model(page, translator, logger).parse(post_url)
        except KeyboardInterrupt:
            raise
        except Exception:
            # try next page ayout
            continue
        if listing.description:
            return listing
        if fallback is None:
            fallback = listing
    return fallback
