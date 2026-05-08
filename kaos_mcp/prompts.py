"""MCP workflow prompts for KAOS.

Prompts teach agents multi-step workflows. They show up as slash commands
in VS Code and interactive prompts in Claude Code.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def register_prompts(app: FastMCP) -> None:
    """Register all KAOS workflow prompts on the FastMCP app."""

    @app.prompt(name="api-discovery")
    def api_discovery(url: str) -> str:
        """Discover backend API endpoints behind a web application."""
        return (
            f"Discover the backend API endpoints used by {url}. Follow this workflow:\n\n"
            "1. Call `kaos-web-browser-log-requests` with a context_id to enable request logging\n"
            "2. Call `kaos-web-browser-navigate` to load the page in the browser\n"
            "3. Interact with the page (click buttons, fill forms, navigate) "
            "to trigger API calls\n"
            "4. Call `kaos-web-browser-requests` with "
            "`resource_type: 'fetch'` to list XHR/fetch API calls\n"
            "5. Call `kaos-web-browser-get-request` for interesting endpoints "
            "to see full JSON payloads\n\n"
            "Report the discovered API endpoints with their HTTP methods, "
            "URLs, and response shapes."
        )

    @app.prompt(name="extract-document")
    def extract_document(path: str) -> str:
        """Extract and analyze a document (PDF, DOCX, PPTX, XLSX)."""
        return (
            f"Extract and analyze the document at {path}. Follow this workflow:\n\n"
            "1. Determine the file type from the extension\n"
            "2. For PDF: use `kaos-pdf-extract-parse` to extract the full document\n"
            "   For DOCX: use `kaos-office-parse-docx`\n"
            "   For PPTX: use `kaos-office-parse-pptx`\n"
            "   For XLSX: use `kaos-office-parse-xlsx` then `kaos-tabular-describe`\n"
            "3. Use `kaos-pdf-search-document` or `kaos-office-search` to find specific content\n"
            "4. Summarize the document structure, key sections, and findings."
        )

    @app.prompt(name="legal-research")
    def legal_research(topic: str) -> str:
        """Research a legal topic across multiple federal sources."""
        return (
            f"Research the legal topic: {topic}\n\n"
            "Search these sources in parallel:\n"
            "1. `kaos-source-fr-search` — Federal Register rules and notices\n"
            "2. `kaos-source-ecfr-search-structure` — Code of Federal Regulations sections\n"
            "3. `kaos-source-edgar-search` — SEC filings (if securities-related)\n"
            "4. `kaos-web-search` — general web search for context\n\n"
            "For promising results:\n"
            "- Use `kaos-source-fr-get-content` to read Federal Register documents\n"
            "- Use `kaos-source-ecfr-content` to read CFR sections\n"
            "- Use `kaos-web-get-markdown` to read web pages\n\n"
            "Synthesize findings into a brief research memo with citations."
        )

    @app.prompt(name="crawl-and-extract")
    def crawl_and_extract(url: str) -> str:
        """Crawl a website and extract structured data."""
        return (
            f"Crawl {url} and extract structured data. Follow this workflow:\n\n"
            "1. Use `kaos-web-discover-urls` to find all pages on the site\n"
            "2. Use `kaos-web-get-links` to understand the site structure\n"
            "3. Use `kaos-web-batch-fetch` on the most relevant URLs\n"
            "4. If there are data tables, use `kaos-web-get-tables` to extract them\n"
            "5. For extracted tables, use `kaos-tabular-register` and `kaos-tabular-query` "
            "to query the data with SQL\n\n"
            "Report what you found: page count, data tables, key content areas."
        )

    @app.prompt(name="company-research")
    def company_research(company: str) -> str:
        """Research a company using SEC EDGAR and web sources."""
        return (
            f"Research {company} using SEC EDGAR filings and public sources.\n\n"
            "1. Use `kaos-source-edgar-lookup` to find the company's CIK from its ticker\n"
            "2. Use `kaos-source-edgar-company` to get recent filings "
            "(filter to 10-K for annual reports, 10-Q for quarterly)\n"
            "3. Use `kaos-source-fr-search` to find Federal Register mentions\n"
            "4. Use `kaos-web-search` for recent news and context\n"
            "5. Use `kaos-web-get-markdown` to read key articles\n\n"
            "Compile a brief company profile: business description, recent filings, "
            "regulatory activity, and key news."
        )
