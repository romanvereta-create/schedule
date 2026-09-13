"""Verified, encrypted daily backups for TEMLI persistent storage."""
import argparse
import datetime
import hashlib
import json
import os
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from cryptography.fernet import Fernet

REQUIRED_ENV = ("TEMLI_GOOGLE_CLIENT_ID","TEMLI_GOOGLE_CLIENT_SECRET","TEMLI_GOOGLE_REFRESH_TOKEN","TEMLI_GOOGLE_FOLDER_ID","TEMLI_BACKUP_ENCRYPTION_KEY")
PREFIX = "temli-backup-"

def configured(environ=None):
    values = os.environ if environ is None else environ
    return all(values.get(name, "").strip() for name in REQUIRED_ENV)

def _env(name):
    value=os.getenv(name,"").strip()
    if not value: raise RuntimeError("missing_"+name.lower())
    return value

def _token():
    data=urllib.parse.urlencode({"client_id":_env("TEMLI_GOOGLE_CLIENT_ID"),"client_secret":_env("TEMLI_GOOGLE_CLIENT_SECRET"),"refresh_token":_env("TEMLI_GOOGLE_REFRESH_TOKEN"),"grant_type":"refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token",data=data),timeout=30) as response:
        return json.load(response)["access_token"]

def _request(url,token,data=None,method=None,content_type=None):
    headers={"Authorization":"Bearer "+token}
    if content_type: headers["Content-Type"]=content_type
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=headers,method=method),timeout=120) as response:
        raw=response.read()
        return json.loads(raw) if raw else {}

def verify_plain_archive(path, inspector):
    with tempfile.TemporaryDirectory(prefix="temli-backup-check-") as temporary:
        destination=Path(temporary)
        with tarfile.open(path,"r:gz") as archive:
            members=archive.getmembers(); seen=set()
            for member in members:
                part=PurePosixPath(member.name); folded=str(part).casefold()
                unsafe=(part.is_absolute() or ".." in part.parts or "\\" in member.name or ":" in member.name or not part.parts or part.parts[0]!="temli" or not (member.isfile() or member.isdir()) or folded in seen)
                if unsafe: raise RuntimeError("unsafe_archive_entry")
                seen.add(folded)
            archive.extractall(destination,filter="data")
        report=inspector(destination/"temli",check_key=False)
        if report.get("status")!="ok": raise RuntimeError("backup_verification_failed:"+",".join(report.get("errors",[])))
        return report

def _upload(path):
    token=_token(); boundary="temli-"+hashlib.sha256(os.urandom(16)).hexdigest()
    metadata=json.dumps({"name":path.name,"parents":[_env("TEMLI_GOOGLE_FOLDER_ID")]}).encode(); content=path.read_bytes(); marker=boundary.encode()
    body=b"--"+marker+b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"+metadata+b"\r\n--"+marker+b"\r\nContent-Type: application/octet-stream\r\n\r\n"+content+b"\r\n--"+marker+b"--\r\n"
    result=_request("https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,size",token,body,"POST","multipart/related; boundary="+boundary)
    query=urllib.parse.quote("'"+_env("TEMLI_GOOGLE_FOLDER_ID")+"' in parents and trashed=false and name contains '"+PREFIX+"'")
    listing=_request("https://www.googleapis.com/drive/v3/files?q="+query+"&fields=files(id,name,createdTime)&orderBy=createdTime%20desc&pageSize=100",token)
    for old in listing.get("files",[])[30:]:
        _request("https://www.googleapis.com/drive/v3/files/"+old["id"],token,method="DELETE")
    return result

def create(host, now=None, upload=True):
    from verify_live_storage import inspect_storage
    root=Path(host.BASE_DIR).resolve()
    output=Path(os.getenv("TEMLI_BACKUP_LOCAL_DIR","/app/data/temli-backups")).resolve()
    if output==root or output.is_relative_to(root): raise RuntimeError("backup_dir_inside_storage")
    output.mkdir(parents=True,exist_ok=True)
    stamp=(now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    plain=output/("."+PREFIX+stamp+".tar.gz.tmp"); final=output/(PREFIX+stamp+".tar.gz.enc")
    try:
        with host.DATA_LOCK:
            with tarfile.open(plain,"w:gz") as archive:
                archive.add(root,arcname="temli")
        report=verify_plain_archive(plain,inspect_storage)
        final.write_bytes(Fernet(_env("TEMLI_BACKUP_ENCRYPTION_KEY")).encrypt(plain.read_bytes()))
        remote=_upload(final) if upload else {"id":"not-uploaded"}
        locals_=sorted(output.glob(PREFIX+"*.tar.gz.enc"),key=lambda item:item.stat().st_mtime,reverse=True)
        for old in locals_[7:]: old.unlink()
        state={"date":(now or datetime.datetime.now()).date().isoformat(),"archive":final.name,"sha256":hashlib.sha256(final.read_bytes()).hexdigest(),"drive_file_id":remote["id"],"lesson_records":report["lesson_records"],"student_records":report["student_records"]}
        (output/"last-success.json").write_text(json.dumps(state,indent=2),encoding="utf-8")
        return dict(status="ok",**state)
    finally:
        plain.unlink(missing_ok=True)

def restore(encrypted,destination,confirm):
    from verify_live_storage import inspect_storage
    if confirm!="RESTORE": raise RuntimeError("confirmation_required")
    destination=Path(destination).resolve()
    if destination.exists(): raise RuntimeError("destination_must_not_exist")
    destination.mkdir(parents=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz",delete=False) as temporary:
        plain=Path(temporary.name); temporary.write(Fernet(_env("TEMLI_BACKUP_ENCRYPTION_KEY")).decrypt(Path(encrypted).read_bytes()))
    try:
        verify_plain_archive(plain,inspect_storage)
        with tarfile.open(plain,"r:gz") as archive: archive.extractall(destination,filter="data")
        return inspect_storage(destination/"temli",check_key=False)
    except Exception:
        try: destination.rmdir()
        except OSError: pass
        raise
    finally: plain.unlink(missing_ok=True)

def start_worker(host):
    if not configured():
        print("TEMLI automatic backup: disabled (environment is incomplete)",flush=True); return None
    def work():
        while True:
            try:
                timezone=getattr(host,"TIMEZONE_NAME","Europe/Moscow")
                try:
                    import pytz
                    now=datetime.datetime.now(pytz.timezone(timezone))
                except Exception: now=datetime.datetime.now()
                output=Path(os.getenv("TEMLI_BACKUP_LOCAL_DIR","/app/data/temli-backups"))
                state={}
                try: state=json.loads((output/"last-success.json").read_text(encoding="utf-8"))
                except (OSError,ValueError): pass
                if state.get("date")!=now.date().isoformat():
                    result=create(host,now)
                    print("TEMLI automatic backup: ok "+result["archive"],flush=True)
            except Exception as error:
                print("TEMLI automatic backup: failed "+type(error).__name__,flush=True)
            time.sleep(900)
    thread=threading.Thread(target=work,name="temli-backup-worker",daemon=True);thread.start();return thread

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest="command",required=True)
    create_cmd=sub.add_parser("create")
    restore_cmd=sub.add_parser("restore");restore_cmd.add_argument("archive");restore_cmd.add_argument("--destination",required=True);restore_cmd.add_argument("--confirm",required=True)
    args=parser.parse_args()
    if args.command=="create":
        import bot
        result=create(bot)
    else: result=restore(args.archive,args.destination,args.confirm)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
