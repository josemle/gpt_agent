import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from loguru import logger
from scrapingbee import ScrapingBeeClient

from reworkd_platform.schemas.workflow.base import Block, BlockIOBase
from reworkd_platform.services.anthropic import HumanAssistantPrompt, ClaudeService
from reworkd_platform.services.serp import SerpService
from reworkd_platform.services.sockets import websockets
from reworkd_platform.settings import settings, Settings


class ContentRefresherInput(BlockIOBase):
    url: str
    competitors: Optional[str] = None


class ContentRefresherOutput(ContentRefresherInput):
    original_report: str
    refreshed_report: str
    refreshed_bullet_points: str


class ContentRefresherAgent(Block):
    type = "ContentRefresherAgent"
    description = "Refresh the content on an existing page"
    input: ContentRefresherInput

    async def run(self, workflow_id: str, **kwargs: Any) -> ContentRefresherOutput:
        def log(msg: Any) -> None:
            websockets.log(workflow_id, msg)

        logger.info(f"Starting {self.type}")
        log(f"Starting {self.type} for {self.input.url}")
        return await ContentRefresherService(settings, log).refresh(self.input)


class ContentRefresherService:
    def __init__(self, settings: Settings, log: Callable[[str], None]):
        self.log = log
        self.claude = ClaudeService(api_key=settings.anthropic_api_key)
        self.scraper = ScrapingBeeClient(api_key=settings.scrapingbee_api_key)
        self.serp = SerpService(api_key=settings.serp_api_key)

    async def refresh(self, input_: ContentRefresherInput) -> ContentRefresherOutput:
        target_url = input_.url

        target_content = await self.get_page_content(target_url)
        self.log("Extracting content from provided URL")

        keywords = await self.find_content_kws(target_content)
        self.log("Finding keywords from source content")
        self.log("Keywords: " + ", ".join(keywords.split(",")))

        sources = self.search_results(keywords)
        sources = [
            source for source in sources if source["url"] != target_url
        ]  # TODO: check based on content overlap

        self.log("Finding sources to refresh content")
        self.log(
            "\n".join([f"- {source['title']}: {source['url']}" for source in sources])
        )

        if input_.competitors:
            self.log("Removing competitors from sources")
            competitors = input_.competitors.split(",")
            sources = self.remove_competitors(sources, competitors, self.log)

        for source in sources[:3]:  # TODO: remove limit of 3 sources
            source["content"] = await self.get_page_content(source["url"])

        source_contents = [
            source for source in sources if source.get("content", None) is not None
        ]

        new_info = [
            await self.find_new_info(target_content, source_content, self.log)
            for source_content in source_contents
        ]

        new_infos = "\n\n".join(new_info)
        self.log("Extracting new, relevant information not present in your content")
        for info in new_info:
            self.log(info)

        self.log("Updating provided content with new information")
        updated_target_content = await self.add_info(target_content, new_infos)
        self.log("Content refresh concluded")

        return ContentRefresherOutput(
            **input_.dict(),
            original_report=target_content,
            refreshed_report=updated_target_content,
            refreshed_bullet_points=new_infos,
        )

    async def get_page_content(self, url: str) -> str:
        page = requests.get(url)
        if page.status_code != 200:
            page = self.scraper.get(url)

        html = BeautifulSoup(page.content, "html.parser")

        pgraphs = html.find_all("p")
        pgraphs = "\n".join(
            [
                f"{i + 1}. " + re.sub(r"\s+", " ", p.text).strip()
                for i, p in enumerate(pgraphs)
            ]
        )

        prompt = HumanAssistantPrompt(
            human_prompt=f"Below is a numbered list of the text in all the <p> tags on a web page:\n{pgraphs}\nSome of these lines may not be part of the main content of the page (e.g. footer text, ads, etc). Please state the line numbers that *are* part of the main content (i.e. the article's paragraphs) as a single consecutive range. Strictly, do not include more info than the line numbers (e.g. 'lines 5-25').",
            assistant_prompt="Based on the text provided, here is the line number range of the main content:",
        )

        line_nums = await self.claude.completion(
            prompt=prompt,
            max_tokens_to_sample=500,
            temperature=0,
        )

        if len(line_nums) == 0:
            return ""

        pgraphs = pgraphs.split("\n")
        content = []
        for line_num in line_nums.split(","):
            if "-" in line_num:
                start, end = self.extract_initial_line_numbers(line_num)
                if start and end:
                    for i in range(start, end + 1):
                        text = ".".join(pgraphs[i - 1].split(".")[1:]).strip()
                        content.append(text)
            elif line_num.isdigit():
                text = ".".join(pgraphs[int(line_num) - 1].split(".")[1:]).strip()
                content.append(text)

        return "\n".join(content)

    def extract_initial_line_numbers(
        self, line_nums: str
    ) -> Tuple[Optional[int], Optional[int]]:
        match = re.search(r"(\d+)-(\d+)", line_nums)
        if match:
            return int(match.group(1)), int(match.group(2))
        else:
            return None, None

    async def find_content_kws(self, content: str) -> str:
        # Claude: find search keywords that content focuses on
        prompt = HumanAssistantPrompt(
            human_prompt=f"Below is content from a web article:\n{content}\nPlease list the keywords that best describe the content of the article. Comma-separate the keywords so we can use them to query a search engine effectively.",
            assistant_prompt="Here is a short search query that best matches the content of the article:",
        )

        return await self.claude.completion(
            prompt=prompt,
            max_tokens_to_sample=20,
        )

    def search_results(self, search_query: str) -> List[Dict[str, str]]:
        source_information = [
            {
                "url": result.get("link", None),
                "title": result.get("title", None),
                "date": result.get("date", None),
            }
            for result in self.serp.search(search_query).get("organic", [])
        ]
        return source_information

    async def find_new_info(
        self, target: str, source: Dict[str, str], log: Callable[[str], None]
    ) -> str:
        source_metadata = f"{source['url']}, {source['title']}" + (
            f", {source['date']}" if source["date"] else ""
        )
        source_content = source["content"]

        # Claude: info mentioned in source that is not mentioned in target
        prompt = HumanAssistantPrompt(
            human_prompt=f"Below is the TARGET article:\n{target}\n----------------\nBelow is the SOURCE article:\n{source_content}\n----------------\nIn a bullet point list, identify all facts, figures, or ideas that are mentioned in the SOURCE article but not in the TARGET article.",
            assistant_prompt="Here is a list of claims in the SOURCE that are not in the TARGET:",
        )
        log(f"Identifying new details to refresh with from '{source['title']}'")

        response = await self.claude.completion(
            prompt=prompt,
            max_tokens_to_sample=5000,
        )

        new_info = "\n".join(response.split("\n\n"))
        new_info += "\n\nSource: " + source_metadata
        return new_info

    async def add_info(self, target: str, info: str) -> str:
        # Claude: rewrite target to include the info
        prompt = HumanAssistantPrompt(
            human_prompt=f"Below are notes from some SOURCE articles:\n{info}\n----------------\nBelow is the TARGET article:\n{target}\n----------------\nPlease rewrite the TARGET article to include the information from the SOURCE articles, the format of the article you write should STRICTLY be the same as the TARGET article. Don't remove any details from the TARGET article, unless you are refreshing that specific content with new information. After any new source info that is added to target, include inline citations using the following example format: 'So this is a cited sentence at the end of a paragraph[1](https://www.wisnerbaum.com/prescription-drugs/gardasil-lawsuit/, Gardasil Vaccine Lawsuit Update August 2023 - Wisner Baum).' Do not cite info that already existed in the TARGET article. Do not list citations separately at the end of the response",
            assistant_prompt="Here is a rewritten version of the target article that incorporates relevant information from the source articles:",
        )

        return await self.claude.completion(
            prompt=prompt,
            max_tokens_to_sample=5000,
        )

    @staticmethod
    def remove_competitors(
        sources: List[Dict[str, str]],
        competitors: List[str],
        log: Callable[[str], None],
    ) -> List[Dict[str, str]]:
        normalized_competitors = [comp.replace(" ", "").lower() for comp in competitors]
        competitor_pattern = re.compile(
            "|".join(re.escape(comp) for comp in normalized_competitors)
        )
        filtered_sources = []
        for source in sources:
            if competitor_pattern.search(
                source["url"].replace(" ", "").lower()
            ) or competitor_pattern.search(source["title"].replace(" ", "").lower()):
                log(f"Removing competitive source: '{source['title']}'")
            else:
                filtered_sources.append(source)

        return filtered_sources
