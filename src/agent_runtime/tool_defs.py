"""LiteLLM tool schemas for the translation agent."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_pdf_info",
            "description": "Get basic PDF metadata: page count, title, author, file size.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Path to the PDF file"}
                },
                "required": ["pdf_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_text",
            "description": "Extract all visible text from one PDF page as plain text. Returns the raw text content of the page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Path to the PDF file"},
                    "page_num": {"type": "integer", "description": "Page number (1-indexed)"}
                },
                "required": ["pdf_path", "page_num"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_blocks",
            "description": "Extract structured text blocks from a page. By default returns text-only (compact). Set verbose=true to include bounding boxes, font size, and bold/italic flags for detailed layout analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Path to the PDF file"},
                    "page_num": {"type": "integer", "description": "Page number (1-indexed)"},
                    "verbose": {"type": "boolean", "description": "Include bbox, font_size, is_bold for layout analysis (default false)"}
                },
                "required": ["pdf_path", "page_num"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_as_image",
            "description": "Render a PDF page as a PNG image file. Use this to visually understand page layout, multi-column structure, table placement, and figure positions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Path to the PDF file"},
                    "page_num": {"type": "integer", "description": "Page number (1-indexed)"},
                    "output_dir": {"type": "string", "description": "Directory to save the rendered image"},
                    "dpi": {"type": "integer", "description": "Image resolution (default 150)"}
                },
                "required": ["pdf_path", "page_num", "output_dir"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_pdfimages",
            "description": "Extract ALL embedded images from the PDF using the pdfimages command (poppler-utils). Images are saved as PNG files to the output directory. Use when you need to extract figures, diagrams, or photos embedded in the PDF.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Path to the PDF file"},
                    "output_dir": {"type": "string", "description": "Directory to save extracted images"},
                    "prefix": {"type": "string", "description": "Filename prefix for extracted images (default 'img')"}
                },
                "required": ["pdf_path", "output_dir"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_page_images",
            "description": "Extract embedded raster images from a specific page using PyMuPDF. Use this as an alternative to run_pdfimages when you only need images from specific pages, or when pdfimages is not available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {"type": "string", "description": "Path to the PDF file"},
                    "page_num": {"type": "integer", "description": "Page number (1-indexed)"},
                    "output_dir": {"type": "string", "description": "Directory to save extracted images"}
                },
                "required": ["pdf_path", "page_num", "output_dir"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "Read a saved image file and return its content as a base64 data URL. Use this to visually inspect extracted images (figures, diagrams, charts) and understand what they contain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "Path to the image file (e.g., 'figures/img-000.png')"}
                },
                "required": ["image_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of any text file. Use this to inspect intermediate results, configuration files, or any text-based content in the working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_tex_file",
            "description": "Write or overwrite a .tex file with the given LaTeX content. The content should be a complete, self-contained, compilable .tex file including \\documentclass, preamble (\\usepackage), and \\begin{document}...\\end{document}. This is the MAIN tool for saving your translation output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tex_path": {"type": "string", "description": "Path where the .tex file should be saved"},
                    "content": {"type": "string", "description": "Complete LaTeX document content"}
                },
                "required": ["tex_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_tex_file",
            "description": "Read the content of a .tex file. Use this when fixing compilation errors: read the current .tex, analyze the error, and write a corrected version.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tex_path": {"type": "string", "description": "Path to the .tex file to read"}
                },
                "required": ["tex_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return its stdout and stderr. Use this for command-line tools like pdftotext, pdfinfo, pdfimages, or other utilities. Note: the command runs in the working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Command timeout in seconds (default 60)"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compile_tex_to_pdf",
            "description": "Compile a .tex file to PDF using the Tectonic compiler (XeLaTeX engine). Automatically copies CJK fonts and configures fontconfig. Returns detailed error information on failure so you can fix and recompile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tex_path": {"type": "string", "description": "Path to the .tex file to compile"},
                    "output_dir": {"type": "string", "description": "Directory where the output PDF should be placed"}
                },
                "required": ["tex_path", "output_dir"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_font_info",
            "description": "Get information about available fonts for the target language. Returns the CJK font filename and family name to use in \\setCJKmainfont. Call this once at the start of translation to know what fonts are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_lang": {"type": "string", "description": "Target language code (e.g., 'chinese', 'japanese', 'korean')"}
                },
                "required": ["target_lang"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List all files in a directory. Use this to verify extracted images, check working directory state, or find output files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {"type": "string", "description": "Path to the directory to list"}
                },
                "required": ["dir_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "translation_complete",
            "description": "Call this tool ONLY when the translation is fully complete and the final PDF has been successfully compiled and verified. This signals the agent to stop and return the output PDF path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "output_pdf_path": {"type": "string", "description": "Path to the final output PDF file"},
                    "summary": {"type": "string", "description": "Brief summary of what was accomplished"}
                },
                "required": ["output_pdf_path", "summary"]
            }
        }
    }
]


# Map tool names to their definitions for quick lookup
TOOL_NAME_MAP = {t["function"]["name"]: t for t in TOOL_DEFINITIONS}
