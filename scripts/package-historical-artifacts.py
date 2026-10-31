"""Publish safe receipts and encrypt raw research records for the local owner."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--public',type=Path,required=True)
    p.add_argument('--recipient',type=Path,required=True);p.add_argument('--label',required=True)
    args=p.parse_args();args.public.mkdir(parents=True,exist_ok=True)
    raw=args.public.parent/(args.label+'.raw.zip')
    with zipfile.ZipFile(raw,'x',compression=zipfile.ZIP_DEFLATED)as archive:
        for file in sorted(args.input.rglob('*')):
            if file.is_file():archive.write(file,file.relative_to(args.input))
    encrypted=args.public/(args.label+'.raw.cms')
    subprocess.run(['openssl','cms','-encrypt','-binary','-aes-256-cbc','-in',str(raw),
        '-outform','DER','-out',str(encrypted),str(args.recipient)],check=True,timeout=60)
    safe=list(args.input.rglob('*.public.json'))
    safe.extend(path for name in ('installed.json','container-launch.json')
                if (path:=args.input/name).is_file())
    for path in safe:
        shutil.copyfile(path,args.public/(args.label+'-'+path.name))
    receipt=dict(schema='tomolab-historical-artifact-envelope-v1',label=args.label,
        raw_archive_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
        encrypted_archive_sha256=hashlib.sha256(encrypted.read_bytes()).hexdigest(),
        recipient_certificate_sha256=hashlib.sha256(args.recipient.read_bytes()).hexdigest(),
        algorithm='OPENSSL_CMS_AES_256_CBC_RSA_3072',private_key_uploaded=False,
        plaintext_raw_uploaded=False)
    (args.public/(args.label+'-envelope.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))


if __name__=='__main__':main()
