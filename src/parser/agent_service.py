"""HTTP/JSON and MCP transports for the same read-only query methods."""
import argparse
import json
from .agent_data import AgentData, prepare

TOOLS = ('get_dataset_info','search_sections','get_section','get_amendments','get_pending_changes')


def create_app(database):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    service = AgentData(database)
    app = FastAPI(title='Oregon Law Agent Data',version='1.0.0',description=service.metadata['notice'])

    async def invalid(request: Request, exc: ValueError):
        return JSONResponse(status_code=400,content={'error':{'code':'invalid_argument','message':str(exc)}})

    async def missing(request: Request, exc: LookupError):
        return JSONResponse(status_code=404,content={'error':{'code':'not_found','message':str(exc)}})

    app.add_exception_handler(ValueError,invalid)
    app.add_exception_handler(LookupError,missing)
    routes = ('dataset','search','section','amendments','pending-changes')
    for name, path in zip(TOOLS,routes):
        app.add_api_route('/v1/'+path,getattr(service,name),methods=['GET'],operation_id=name)
    return app


def create_mcp(database):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    service = AgentData(database)
    server = FastMCP('Oregon Law Agent Data',instructions=service.metadata['notice'])
    for name in TOOLS:
        server.add_tool(getattr(service,name),name=name,
                        annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,idempotentHint=True,openWorldHint=False))
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    build=commands.add_parser('prepare',help='build an indexed serving copy')
    build.add_argument('--source',required=True)
    build.add_argument('--output',required=True)
    for command in ('http','mcp'):
        sub=commands.add_parser(command)
        sub.add_argument('--database',required=True)
        if command=='http':
            sub.add_argument('--host',default='127.0.0.1')
            sub.add_argument('--port',type=int,default=8787)
    args=parser.parse_args()
    if args.command=='prepare':
        print(json.dumps(prepare(args.source,args.output)))
    elif args.command=='http':
        import uvicorn
        uvicorn.run(create_app(args.database),host=args.host,port=args.port)
    else:
        create_mcp(args.database).run(transport='stdio')


if __name__=='__main__':
    main()
