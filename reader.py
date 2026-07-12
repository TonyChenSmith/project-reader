"""
一个基于 AI 的项目阅读与分析交互工具。
@author Tony Chen Smith
@date 2026-05-25
@version 1.2.0
"""
import chardet
import logging
import json
import os
import re
import sys
import time
import traceback

from collections import deque
from datetime import datetime
from dotenv import load_dotenv
from itertools import islice
from openai import OpenAI
from pathlib import Path
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.rule import Rule

load_dotenv(override=True)

log_tags={
    logging.CRITICAL:"F",
    logging.ERROR:"E",
    logging.WARNING:"W",
    logging.INFO:"I",
    logging.DEBUG:"D",
    logging.NOTSET:"N",
}

#文件操作根
root=Path.cwd()

class ReaderFormatter(logging.Formatter):
    """
    阅读日志格式器。
    """
    def formatTime(self,record,datefmt=None):
        ct=datetime.fromtimestamp(record.created)
        return ct.strftime("%Y-%m-%d %H:%M:%S")+f":{ct.microsecond//1000:03d}"
    
    def format(self,record):
        timestamp=self.formatTime(record)
        prefix=f"[{timestamp}][{log_tags.get(record.levelno,"U")}][{getattr(record,"role","S")}] "
        indent=" "*len(prefix)

        message=record.getMessage()
        lines=message.split("\n")
        result=f"{prefix}{lines[0]}"
        for line in lines[1:]:
            result+="\n"+indent+line
        return result

#辅助函数区域

def check_safe_path(path):
    """
    检测路径是否为可达安全路径。
    """
    p=Path(path)
    if p.is_absolute():
        return f"error:路径'{path}'是绝对路径，必须传入相对于项目根目录'{root}'的相对路径。",None
    target=(root/p).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        return f"error:路径'{path}'展开为'{target}'超出项目根目录'{root}'的管辖范围，已拒绝。",None
    
    return None,target

def check_is_text(data):
    """
    检测数据内容是否代表文本信息。是返回真。
    """
    if len(data)==0:
        return True,"utf-8"

    null_count=data.count(0x00)
    if null_count>len(data)*0.01:
        return False,None

    detect_result=chardet.detect(data)
    encoding=detect_result.get("encoding")
    confidence=detect_result.get("confidence",0)

    if encoding is not None and confidence>=0.7:
        try:
            data.decode(encoding)
            return True,encoding
        except (UnicodeDecodeError,LookupError):
            pass
    
    return False,None

#工具函数区域

def get_current_time()->str:
    """
    获取当前日期时间及完整时区信息。
    返回格式为 time:{iso:ISO8601含偏移,tz:时区缩写,dst:0/1,unix:秒戳,day:中文星期}。
    """
    now=datetime.now().astimezone()
    tz_name=time.tzname[0] if time.localtime().tm_isdst==0 else time.tzname[1]
    is_dst="1" if time.localtime().tm_isdst else "0"
    unix_ts=int(time.time())
    days=["周一","周二","周三","周四","周五","周六","周日"]
    day=days[now.weekday()]
    iso=now.isoformat(timespec="seconds")
    return f"time:{{iso:{iso},tz:{tz_name},dst:{is_dst},unix:{unix_ts},day:{day}}}"

def list_directory(dir:str,start:int=1,n:int=50)->str:
    """
    列出指定相对目录下的所有条目。
    返回格式为 list:{dir:规范相对路径,start:起始索引,n:实际返回数,items:[条目名,...]}，
    条目名为纯文件名，逗号分隔，目录后缀'/'以区分类型。
    start从1开始，n为返回条目数，默认50，上限3000。
    """
    if start<1:
        start=1
    if n<=0 or n>3000:
        n=3000
    msg,target=check_safe_path(dir)
    if msg:
        return msg

    if not target.exists():
        return f"error:路径'{dir}'不存在。"
    if not target.is_dir():
        return f"error:路径'{dir}'不是目录。"

    try:
        items=[]
        with os.scandir(target) as it:
            for entry in islice(it,start-1,start-1+n):
                name=entry.name
                if entry.is_dir():
                    name+='/'
                items.append(name)
    except Exception as e:
        return f"error:列出目录条目触发{e}。"

    return f"list:{{dir:{str(target.relative_to(root))},start:{start},n:{len(items)},items:[{','.join(items)}]}}"

def read_text_file(file:str,start:int=1,n:int=50)->str:
    """
    读取文本文件的指定行范围。文件路径为相对于项目根目录的相对路径。
    使用chardet自动探测编码(置信度不足时回退utf-8)。
    返回格式为 read:{file:相对路径,start:起始行,n:实际行数,text:"行1\n行2\n..."}。
    n为读取行数，默认50，上限3000。start小于1时自动修正为1。
    若文件为空返回n为0且text为空字符串。出错返回error:前缀的错误信息。
    """
    if start<1:
        start=1
    if n<=0 or n>3000:
        n=3000
    msg,target=check_safe_path(file)
    if msg:
        return msg

    if not target.exists():
        return f"error:路径'{file}'不存在。"
    if target.is_dir():
        return f"error:路径'{file}'是目录。"

    try:
        with open(target,"rb") as f:
            raw=f.read(8192)
    except Exception as e:
        return f"error:路径'{file}'读取触发{e}。"

    _,encoding=check_is_text(raw)
    if encoding is None:
        encoding="utf-8"

    try:
        with open(target,"r",encoding=encoding,errors="replace") as f:
            selected=list(islice(f,start-1,start-1+n))
    except Exception as e:
        return f"error:路径'{file}'以编码'{encoding}'打开触发{e}。"

    text_str="".join(selected).replace('"','\\"')
    rel=str(target.relative_to(root))
    return f'read:{{file:{rel},start:{start},n:{len(selected)},text:"{text_str}"}}'

def search_files(pattern:str,dir:str=".",glob:str="*",limit:int=50)->str:
    """
    在指定目录下用正则表达式搜索文件内容，返回至少有一行匹配的文件列表。
    返回格式为 file:[相对路径,...]。pattern仅支持单行匹配，禁止含\n等跨行模式。
    dir为搜索目录(默认'.')，glob为文件名匹配模式(默认'*')，limit为最大结果数(默认50)。
    """
    if "\n" in pattern or "\r" in pattern:
        return f"error:pattern含换行符，search_files仅支持单行匹配。"

    msg,target=check_safe_path(dir)
    if msg:
        return msg

    if not target.exists():
        return f"error:路径'{dir}'不存在。"
    if not target.is_dir():
        return f"error:路径'{dir}'不是目录。"

    try:
        regex=re.compile(pattern)
    except re.error as e:
        return f"error:正则'{pattern}'编译失败触发{e}。"

    try:
        entries=target.glob(glob)
    except Exception as e:
        return f"error:glob模式'{glob}'展开触发{e}。"

    results=[]
    for fpath in entries:
        if not fpath.is_file():
            continue
        if len(results)>=limit:
            break

        try:
            with open(fpath,"rb") as f:
                raw=f.read(8192)
        except Exception:
            continue

        _,encoding=check_is_text(raw)
        if encoding is None:
            encoding="utf-8"

        try:
            with open(fpath,"r",encoding=encoding,errors="replace") as f:
                for line in f:
                    if regex.search(line):
                        results.append(str(fpath.relative_to(root)))
                        break
        except Exception:
            continue

    return f"file:[{','.join(results)}]"

def search_content(pattern:str,file:str,start:int=1,n:int=-1,limit:int=50,context:int=0)->str:
    """
    在指定文件中用正则表达式逐行搜索匹配行，支持行区间和上下文。
    返回格式为 content:{file:相对路径,results:[{start:起始行,n:块行数,text:"文本块"},...]}。
    pattern仅支持单行匹配，禁止含\n等跨行模式。
    file为文件路径，start约束命中行号(默认1)，n为搜索行数(-1到末尾)，
    limit为最大命中数(默认50)，context为各命中前后上下文行数(默认0，上限20)。
    """
    if "\n" in pattern or "\r" in pattern:
        return f"error:pattern含换行符，search_content仅支持单行匹配。"

    if start<1:
        start=1
    if context<0:
        context=0
    if context>20:
        context=20
    msg,target=check_safe_path(file)
    if msg:
        return msg

    if not target.exists():
        return f"error:路径'{file}'不存在。"
    if target.is_dir():
        return f"error:路径'{file}'是目录。"

    try:
        regex=re.compile(pattern)
    except re.error as e:
        return f"error:正则'{pattern}'编译失败触发{e}。"

    try:
        with open(target,"rb") as f:
            raw=f.read(8192)
    except Exception as e:
        return f"error:路径'{file}'读取触发{e}。"

    _,encoding=check_is_text(raw)
    if encoding is None:
        encoding="utf-8"

    rel=str(target.relative_to(root))
    results=[]
    try:
        with open(target,"r",encoding=encoding,errors="replace") as f:
            read_start=max(1,start-context) if context>0 else start
            end_line=None if n==-1 else start-1+n
            it=islice(f,read_start-1,end_line)
            before=deque(maxlen=context) if context>0 else None
            pending=deque()
            lineno=read_start-1

            while len(results)<limit:
                if pending:
                    cur_ln,line_content=pending.popleft()
                else:
                    try:
                        line_content=next(it)
                        cur_ln=lineno+1
                    except StopIteration:
                        break

                lineno=cur_ln
                line_clean=line_content.rstrip("\n")

                if regex.search(line_clean) and lineno>=start:
                    if context>0:
                        block_start=lineno-len(before)
                        block_lines=list(before)+[line_clean]

                        next_ln=lineno+1
                        for _ in range(context):
                            try:
                                after_line=next(it)
                                block_lines.append(after_line.rstrip("\n"))
                                pending.append((next_ln,after_line))
                                next_ln+=1
                            except StopIteration:
                                break

                        block_n=len(block_lines)
                        block_text="\n".join(block_lines).replace('"','\\"')
                        results.append(
                            f'{{"start":{block_start},"n":{block_n},"text":"{block_text}"}}'
                        )
                    else:
                        text=line_clean.replace('"','\\"')
                        results.append(f'{{"start":{lineno},"n":1,"text":"{text}"}}')
                    if len(results)>=limit:
                        break

                if context>0:
                    before.append(line_clean)
    except Exception as e:
        return f"error:路径'{file}'搜索触发{e}。"

    return f"content:{{file:{rel},results:[{','.join(results)}]}}"

def find_files(glob:str,dir:str=".",limit:int=50)->str:
    """
    按glob模式递归搜索文件，只匹配文件不匹配目录。
    返回格式为find:[相对路径,...]。glob为glob模式(如'**/*.py'、'*.md')，
    dir为搜索起始目录(默认'.')，limit为最大结果数(默认50)。
    """
    msg,target=check_safe_path(dir)
    if msg:
        return msg

    if not target.exists():
        return f"error:路径'{dir}'不存在。"
    if not target.is_dir():
        return f"error:路径'{dir}'不是目录。"

    try:
        entries=target.glob(glob)
    except Exception as e:
        return f"error:glob展开触发{e}。"

    results=[]
    for fpath in entries:
        if not fpath.is_file():
            continue
        if len(results)>=limit:
            break
        results.append(str(fpath.relative_to(root)))

    return f"find:[{','.join(results)}]"

def get_path_info(path:str)->str:
    """
    获取文件或目录的详细信息。返回格式为info:{path:相对路径,type:text/binary/directory/not_found,size:字节数,last:YYYY-MM-DD HH:MM:SS}。
    文本文件额外含lines:行数与encoding:编码，目录额外含entries:直接子条目数。路径不存在则type为not_found。
    """
    msg,target=check_safe_path(path)
    if msg:
        return msg

    rel=str(target.relative_to(root))

    if not target.exists():
        return f"info:{{path:{rel},type:not_found}}"

    st=target.stat()
    last=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    if target.is_dir():
        try:
            entries=sum(1 for _ in target.iterdir())
        except Exception:
            entries=-1
        return f"info:{{path:{rel},type:directory,size:{st.st_size},last:{last},entries:{entries}}}"

    try:
        with open(target,"rb") as f:
            raw=f.read(8192)
    except Exception:
        return f"info:{{path:{rel},type:binary,size:{st.st_size},last:{last}}}"

    is_text,encoding=check_is_text(raw)
    if not is_text:
        return f"info:{{path:{rel},type:binary,size:{st.st_size},last:{last}}}"

    try:
        with open(target,"r",encoding=encoding,errors="replace") as f:
            lines=sum(1 for _ in f)
    except Exception:
        lines=-1

    return f"info:{{path:{rel},type:text,size:{st.st_size},last:{last},lines:{lines},encoding:{encoding}}}"

def get_project_root()->str:
    """
    返回当前项目根目录的绝对路径字符串。
    """
    return f"root:{str(root)}"

def get_self_path()->str:
    """
    返回reader.py自身的绝对路径。
    """
    return f"self:{str(Path(__file__).resolve())}"

#工具字典
tool_func={
    "get_current_time":get_current_time,
    "list_directory":list_directory,
    "read_text_file":read_text_file,
    "search_files":search_files,
    "search_content":search_content,
    "find_files":find_files,
    "get_path_info":get_path_info,
    "get_project_root":get_project_root,
    "get_self_path":get_self_path
}

#工具声明
tools=[
    {
        "type":"function",
        "function":
        {
            "name":"get_current_time",
            "description":"获取当前日期时间及完整时区信息，返回格式为 time:{iso:ISO8601含偏移,tz:时区,dst:0/1,unix:秒,day:周}。",
            "parameters":
            {
                "type":"object",
                "properties":{}
            },
            "required":[]
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"list_directory",
            "description":"列出指定相对目录下的所有条目。返回格式为 list:{dir:规范相对路径,start:起始索引,n:实际返回数,items:[条目名,...]}，条目名为纯文件名，逗号分隔，目录后缀'/'以区分类型。start从1开始，n为返回条目数，默认50，上限3000。",
            "parameters":
            {
                "type":"object",
                "properties":
                {
                    "dir":
                    {
                        "type":"string",
                        "description":"相对于项目根目录的目录路径，例如'.'表示根目录，'src'表示src子目录。"
                    },
                    "start":
                    {
                        "type":"integer",
                        "description":"起始索引，从1开始，默认1。"
                    },
                    "n":
                    {
                        "type":"integer",
                        "description":"返回条目数，默认50，上限3000。"
                    }
                },
                "required":["dir"]
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"read_text_file",
            "description":"读取文本文件的指定行范围。返回格式为 read:{file:相对路径,start:起始行,n:实际行数,text:\"行1\\n行2\\n...\"}。n为读取行数，默认50，上限3000。start从1开始。若文件为空返回n为0且text为空字符串。出错返回error:前缀的错误信息。",
            "parameters":
            {
                "type":"object",
                "properties":
                {
                    "file":
                    {
                        "type":"string",
                        "description":"相对于项目根目录的文件路径，例如'src/main.py'。"
                    },
                    "start":
                    {
                        "type":"integer",
                        "description":"起始行号，大于等于1，默认1。"
                    },
                    "n":
                    {
                        "type":"integer",
                        "description":"读取行数，默认50，上限3000。"
                    }
                },
                "required":["file"]
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"search_files",
            "description":"在指定目录下用正则表达式搜索文件内容，返回至少有一行匹配的文件列表。返回格式为 file:[相对路径,...]。pattern仅支持单行匹配，禁止含\\n等跨行模式。dir为搜索目录(默认'.')，glob为文件名匹配模式(默认'*')，limit为最大结果数(默认50)。",
            "parameters":
            {
                "type":"object",
                "properties":
                {
                    "pattern":
                    {
                        "type":"string",
                        "description":"Python re正则表达式模式，仅支持单行匹配，禁止含\\n。例如'TODO|FIXME'或'def search_'。"
                    },
                    "dir":
                    {
                        "type":"string",
                        "description":"搜索的目标目录，相对于项目根目录，默认'.'。"
                    },
                    "glob":
                    {
                        "type":"string",
                        "description":"文件名匹配模式，例如'*.py'、'**/*.md'，默认'*'。"
                    },
                    "limit":
                    {
                        "type":"integer",
                        "description":"最大返回结果数，默认50。"
                    }
                },
                "required":["pattern"]
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"search_content",
            "description":"在指定文件中用正则表达式逐行搜索匹配行，支持行区间和上下文。返回格式为 content:{file:相对路径,results:[{start:起始行,n:块行数,text:\"文本块\"},...]}。pattern仅支持单行匹配，禁止含\\n等跨行模式。file为文件路径，start约束命中行号(默认1)，n为搜索行数(-1到末尾)，limit为最大命中数(默认50)，context为各命中前后上下文行数(默认0，上限20)。",
            "parameters":
            {
                "type":"object",
                "properties":
                {
                    "pattern":
                    {
                        "type":"string",
                        "description":"Python re正则表达式模式，仅支持单行匹配，禁止含\\n。例如'TODO|FIXME'或'def search_'。"
                    },
                    "file":
                    {
                        "type":"string",
                        "description":"相对于项目根目录的文件路径，例如'src/main.py'。"
                    },
                    "start":
                    {
                        "type":"integer",
                        "description":"命中行号下限，大于等于1，默认1。窗口可低于此值以提供上下文。"
                    },
                    "n":
                    {
                        "type":"integer",
                        "description":"搜索行数，-1表示到文件末尾，默认-1。"
                    },
                    "limit":
                    {
                        "type":"integer",
                        "description":"最大命中数，默认50。"
                    },
                    "context":
                    {
                        "type":"integer",
                        "description":"各命中前后各显示上下文行数，默认0，上限20。设为2则窗口含前2行+命中行+后2行。"
                    }
                },
                "required":["pattern","file"]
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"find_files",
            "description":"按glob模式递归搜索文件，只匹配文件不匹配目录。返回格式为find:[相对路径,...]。glob为glob模式(如'**/*.py'、'*.md')，dir为搜索起始目录(默认'.')，limit为最大结果数(默认50)。",
            "parameters":
            {
                "type":"object",
                "properties":
                {
                    "glob":
                    {
                        "type":"string",
                        "description":"glob匹配模式，例如'**/*.py'、'*.yaml'、'src/**/config.*'。"
                    },
                    "dir":
                    {
                        "type":"string",
                        "description":"搜索起始目录，相对于项目根目录，默认'.'。"
                    },
                    "limit":
                    {
                        "type":"integer",
                        "description":"最大返回结果数，默认50。"
                    }
                },
                "required":["glob"]
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"get_path_info",
            "description":"获取文件或目录的详细信息。返回格式为info:{path:相对路径,type:text/binary/directory/not_found,size:字节数,last:YYYY-MM-DD HH:MM:SS}。文本文件额外含lines:行数与encoding:编码，目录额外含entries:直接子条目数。路径不存在则type为not_found。",
            "parameters":
            {
                "type":"object",
                "properties":
                {
                    "path":
                    {
                        "type":"string",
                        "description":"相对于项目根目录的文件或目录路径，例如'src/main.py'或'.'。"
                    }
                },
                "required":["path"]
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"get_project_root",
            "description":"返回当前项目根目录的绝对路径字符串。",
            "parameters":
            {
                "type":"object",
                "properties":{}
            }
        }
    },
    {
        "type":"function",
        "function":
        {
            "name":"get_self_path",
            "description":"返回reader.py自身的绝对路径。可通过对比此路径与项目根目录，判断reader.py是否在项目管辖范围内从而是否可被读取。",
            "parameters":
            {
                "type":"object",
                "properties":{}
            }
        }
    }
]

def stream_display(response,console,logger):
    """
    流式读取并输出到控制台和日志。、
    """
    reasoning_content=""
    content=""
    calls_dict={}
    has_reasoning=False
    has_content=False
    tokens=0

    try:
        for chunk in response:
            delta=chunk.choices[0].delta
            if getattr(delta,"reasoning_content",None):
                if not has_reasoning:
                    console.print(Rule("[dim]思考[/dim]",style="dim"))
                    logger.info("===开始思考===",extra={"role":"S"})
                    has_reasoning=True
                reasoning_content+=delta.reasoning_content
                console.print(delta.reasoning_content,end="",style="dim")
            if delta.content:
                if has_reasoning and not has_content:
                    logger.info(reasoning_content,extra={"role":"T"})
                    console.print()
                    console.print(Rule("[green]回答[/green]",style="green"))
                    logger.info("===结束思考===",extra={"role":"S"})
                    logger.info("===开始回答===",extra={"role":"S"})
                    has_content=True
                elif not has_reasoning and not has_content:
                    console.print(Rule("[green]回答[/green]",style="green"))
                    logger.info("===开始回答===",extra={"role":"S"})
                    has_content=True
                content+=delta.content
                console.print(delta.content,end="")
            if delta.tool_calls:
                for tool_call_delta in delta.tool_calls:
                    idx=tool_call_delta.index
                    if idx not in calls_dict:
                        calls_dict[idx]={
                            "id":tool_call_delta.id or "",
                            "name":tool_call_delta.function.name if tool_call_delta.function else "",
                            "arguments":""
                        }
                    if tool_call_delta.id:
                        calls_dict[idx]["id"]=tool_call_delta.id
                    if tool_call_delta.function and tool_call_delta.function.name:
                        calls_dict[idx]["name"]=tool_call_delta.function.name
                    if tool_call_delta.function and tool_call_delta.function.arguments:
                        calls_dict[idx]["arguments"]+=tool_call_delta.function.arguments
            if hasattr(chunk,"usage") and chunk.usage:
                tokens=chunk.usage.total_tokens
    except Exception as e:
        if has_reasoning and not has_content:
            logger.info(reasoning_content,extra={"role":"T"})
            logger.error("===思考中断===",extra={"role":"S"})
        elif has_content:
            logger.info(content,extra={"role":"A"})
            logger.error("===回答中断===",extra={"role":"S"})
        console.print()
        console.print(Rule("[red]出错[/red]",style="red"))
        einfo=traceback.format_exc()
        console.print(f"{einfo}",style="red")
        logger.error("===出现错误===",extra={"role":"S"})
        logger.error(f"{einfo}",extra={"role":"S"})
        return None,e,tokens

    console.print()
    if has_content:
        logger.info(content, extra={"role":"A"})
        logger.info("===结束回答===", extra={"role":"S"})
    elif has_reasoning:
        logger.info(reasoning_content, extra={"role":"T"})
        logger.info("===结束思考===", extra={"role":"S"})
    
    if chunk.choices[0].finish_reason=="tool_calls":
        tool_calls_list=[]
        for idx in sorted(calls_dict.keys()):
            tc=calls_dict[idx]
            tool_calls_list.append({
                "id":tc["id"],
                "type":"function",
                "function":{
                    "name":tc["name"],
                    "arguments":tc["arguments"]
                }
            })
        return {"role":"assistant","content":content,"reasoning_content":reasoning_content,"tool_calls":tool_calls_list},None,tokens
    else:
        return {"role":"assistant","content":content,"reasoning_content":reasoning_content},None,tokens

def stream_response(history,console,logger,client,question):
    """
    发起一次流式请求。
    """
    messages=history.copy()
    messages.append({"role":"user","content":question})
    total_token=0

    count=0
    while True:
        response=client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream=True,
            reasoning_effort="high",
            extra_body={"thinking":{"type":"enabled"}},
            stream_options={"include_usage":True},
            tools=tools
        )

        assistant,ex,tokens=stream_display(response,console,logger)
        if ex:
            return None,total_token
        else:
            total_token=tokens
            messages.append(assistant)

            if assistant.get("tool_calls"):
                console.print(Rule("[blue]工具[/blue]",style="blue"))
                logger.info("===工具调用===",extra={"role":"S"})

                for tc in assistant["tool_calls"]:
                    func=tool_func[tc["function"]["name"]]
                    args=json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                    console.print(f"id:{tc['id']},function:{tc['function']['name']},arguments:{args}",style="blue")
                    if count>=1024:
                        result="error:已达到最大工具调用次数，不要再尝试调用工具。"
                    else:
                        try:
                            result=func(**args)
                        except TypeError as e:
                            result=f"error:工具{tc['function']['name']}参数不匹配：{e}，传入参数：{args}。"
                        except Exception as e:
                            result=f"error:工具{tc['function']['name']}执行异常：{e}。"
                    logger.info(f"id:{tc['id']},function:{tc['function']['name']},arguments:{args},result:{result}",extra={"role":"S"})
                    messages.append({"role":"tool","tool_call_id":tc["id"],"content":result})
                
                count=count+1
            else:
                return messages,total_token

token_limit=750000
keep_last=3

def summary_message(console,logger,client,message,tokens):
    """
    总结消息，如不符合条件还是放弃总结。
    """
    if tokens<=token_limit:
        return message
    sys_msgs=[]
    index=0
    while index<len(message) and message[index]["role"]=="system":
        sys_msgs.append(message[index])
        index+=1
    
    rounds=[]
    current=[]
    for msg in message[index:]:
        if msg["role"]=="user"and current:
            rounds.append(current)
            current=[]
        current.append(msg)
    if current:
        rounds.append(current)
    
    if len(rounds)<=keep_last:
        # 放弃总结
        return message
    
    middle=rounds[:-keep_last]
    last=rounds[-keep_last:]

    summary_messages=list(sys_msgs)
    for r in middle:
        summary_messages.extend(r)
    summary_messages.append({"role":"user","content":"请对以上对话历史做简洁摘要，要求尽可能传达所有变动点，保留关键决策、代码变更和未解决的问题。"})

    console.print(Rule("[yellow]消息总结[/yellow]", style="yellow"))
    logger.info("===消息总结===",extra={"role": "S"})

    try:
        summary_resp=client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=summary_messages,
            max_tokens=8196,
            stream=True,
        )
        summary=""
        for chunk in summary_resp:
            if chunk.choices and chunk.choices[0].delta.content:
                content=chunk.choices[0].delta.content
                summary+=content
                console.print(content,style="yellow",end="")
        console.print()
        logger.info(f"{summary}",extra={"role":"S"})
    except Exception as e:
        console.print()
        einfo=traceback.format_exc()
        console.print(f"总结失败：{einfo}",style="yellow")
        logger.info(f"总结失败：{einfo}",extra={"role":"S"})
        return message
    
    result=list(sys_msgs)
    result.append({"role":"user","content":f"【前序对话摘要，共{len(middle)}轮】{summary}"})
    result.append({"role":"assistant","content":"已理解。"})
    for r in last:
        result.extend(r)
    return result

commands=["/help","/new","/repeat","/quit"]

message_prompt={
    "role":"system",
    "content":(
        "你是一个中文助手。思考和回答输出应尽量全用简体中文。"
        "每次寻找依据请优先查找实际文件，你读取的文件是可以在你会话期间改变的。非全文检查请多用搜索，少读全文。"
    )
}

if __name__ == "__main__":
    # 控制台初始化
    console=Console()

    # 日志初始化
    script_dir=Path(__file__).parent.resolve()
    log_dir=script_dir/"log"
    log_dir.mkdir(exist_ok=True)
    log_filename=log_dir/f"project-reader_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    logger=logging.getLogger("project-reader")
    logger.setLevel(logging.INFO)
    handler=logging.FileHandler(log_filename,encoding="utf-8")
    handler.setFormatter(ReaderFormatter())
    logger.addHandler(handler)

    # 参数处理
    if len(sys.argv)>=2:
        raw_path=sys.argv[1]
        p=Path(raw_path)
        if p.exists() and p.is_dir():
            root=p.resolve()
    console.print(Rule("[yellow]环境[/yellow]",style="yellow"))
    console.print(f"项目路径: {root}",style="yellow")
    logger.info("===项目路径===",extra={"role":"S"})
    logger.info(f"{root}",extra={"role":"S"})
    console.print(Rule("[yellow]会话帮助[/yellow]",style="yellow"))
    logger.info("===会话帮助===",extra={"role":"S"})
    console.print("  /help   返回该会话帮助。\n  /new    创建新的会话。\n  /repeat 重复上一次提问。\n  /quit   退出程序。",style="yellow")
    logger.info("  /help   返回该会话帮助。\n  /new    创建新的会话。\n  /repeat 重复上一次提问。\n  /quit   退出程序。",extra={"role":"S"})

    # API客户端初始化
    client=OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY",""),base_url="https://api.deepseek.com")

    history=[message_prompt]
    previous=None
    total=0

    while True:
        console.print(Rule("[cyan]提问[/cyan]",style="cyan"))
        question=prompt('> ',completer=WordCompleter(commands,sentence=True),complete_while_typing=True).strip()

        if question=="/quit":
            console.print(Rule("[yellow]结束[/yellow]",end="",style="yellow"))
            logger.info("===程序结束===",extra={"role":"S"})
            break
        elif question=="/new":
            history.clear()
            history.append(message_prompt)
            console.print(Rule("[yellow]新的会话[/yellow]",style="yellow"))
            console.print("新建会话",style="yellow")
            logger.info("===新的会话===",extra={"role":"S"})
        elif question=="/help":
            console.print(Rule("[yellow]会话帮助[/yellow]",style="yellow"))
            logger.info("===会话帮助===",extra={"role":"S"})
            console.print("  /help   返回该会话帮助。\n  /new    创建新的会话。\n  /repeat 重复上一次提问。\n  /quit   退出程序。",style="yellow")
            logger.info("  /help   返回该会话帮助。\n  /new    创建新的会话。\n  /repeat 重复上一次提问。\n  /quit   退出程序。",extra={"role":"S"})
        elif question=="/repeat":
            if previous:
                console.print(Rule("[yellow]重新提问[/yellow]",style="yellow"))
                console.print(f"> {previous}",style="yellow")
                logger.info("===重新提问===",extra={"role":"S"})
                logger.info(f"{previous}",extra={"role":"S"})

                history=summary_message(console,logger,client,history,total)
                result,tokens=stream_response(history,console,logger,client,previous)
                if result:
                    ratio=tokens/token_limit
                    color="red" if ratio>1 else ("yellow" if ratio>0.8 else "green")
                    console.print(Rule(f"[{color}]会话用量 {tokens}/{token_limit} ({ratio:.2%})[/{color}]",style=color))
                    logger.info(f"会话用量：{tokens}/{token_limit}({ratio:.2%})",extra={"role":"S"})
                    total=tokens
                    history=result
        else:
            logger.info("===开始提问===",extra={"role":"S"})
            logger.info(f"{question}",extra={"role":"U"})

            history=summary_message(console,logger,client,history,total)
            result,tokens=stream_response(history,console,logger,client,question)
            if result:
                ratio=tokens/token_limit
                color="red" if ratio>1 else ("yellow" if ratio>0.8 else "green")
                console.print(Rule(f"[{color}]会话用量 {tokens}/{token_limit} ({ratio:.2%})[/{color}]",style=color))
                logger.info(f"会话用量：{tokens}/{token_limit}({ratio:.2%})",extra={"role":"S"})
                total=tokens
                history=result
            previous=question