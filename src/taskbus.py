from dataclasses import dataclass
import asyncio

from src.log import logger
from src.edncrypt import encrypt_image, decrypt_image

@dataclass(slots=True, kw_only=True)
class Picenc:
    token: str
    image_bytes: bytes
    fut: asyncio.Future[str]

@dataclass(slots=True, kw_only=True)
class Picdec:
    token: str
    file_name: str
    fut: asyncio.Future[bytes]

images_encrypt_task: asyncio.Queue[Picenc] = asyncio.Queue(maxsize=100)
images_decrypt_task: asyncio.Queue[Picdec] = asyncio.Queue(maxsize=50)

encrypt_workers: set[asyncio.Task] = set()
decrypt_workers: set[asyncio.Task] = set()
min_workers = 1
max_workers = 12


async def encrypt_worker(name: str) -> None:
    logger.info(f"{name} started")
    while True:
        try:
            item = await images_encrypt_task.get()
        except asyncio.CancelledError:
            logger.info(f"{name} stopped")
            return
        except Exception:
            logger.exception(f"Encryption Worker encountered an error")
            continue
    
        try:
            file_name = await asyncio.to_thread(
                encrypt_image,
                item.image_bytes,
                item.token
            )
            if not item.fut.done():
                item.fut.set_result(file_name)
        except asyncio.CancelledError:
            logger.info(f"{name} stopped")
            return
        except Exception as e:
            if not item.fut.done():
                item.fut.set_exception(e)
        finally:
            images_encrypt_task.task_done()

async def decrypt_worker(name: str) -> None:
    logger.info(f"{name} started")
    while True:
        try:
            item = await images_decrypt_task.get()
        except asyncio.CancelledError:
            logger.info(f"{name} stopped")
            return
        except Exception:
            logger.exception(f"Decryption Worker encountered an error")
            continue
    
        try:
            image_bytes = await asyncio.to_thread(
                decrypt_image,
                item.file_name,
                item.token
            )
            if not item.fut.done():
                item.fut.set_result(image_bytes)
        except asyncio.CancelledError:
            logger.info(f"{name} stopped")
            return
        except Exception as e:
            if not item.fut.done():
                item.fut.set_exception(e)
        finally:
            images_decrypt_task.task_done()

def encrypt_spawn_one() -> None:
    t = asyncio.create_task(
        encrypt_worker(f"ew{len(encrypt_workers)}")
    )
    encrypt_workers.add(t)
    t.add_done_callback(encrypt_workers.discard)

def decrypt_spawn_one() -> None:
    t = asyncio.create_task(
        decrypt_worker(f"dw{len(decrypt_workers)}")
    )
    decrypt_workers.add(t)
    t.add_done_callback(decrypt_workers.discard)

async def autoscaler() -> None:
    while True:
        try:
            encrypt_q = images_encrypt_task.qsize()
            decrypt_q = images_decrypt_task.qsize()

            encrypt_n = len(encrypt_workers)
            decrypt_n = len(decrypt_workers)

            if encrypt_n < min_workers:
                for _ in range(min_workers - encrypt_n):
                    encrypt_spawn_one()
            if decrypt_n < min_workers:
                for _ in range(min_workers - decrypt_n):
                    decrypt_spawn_one()

            if encrypt_q > encrypt_n and encrypt_n < max_workers:
                for _ in range(min(max_workers - encrypt_n, encrypt_q - encrypt_n)):
                    encrypt_spawn_one()
            if decrypt_q > decrypt_n and decrypt_n < max_workers:
                for _ in range(min(max_workers - decrypt_n, decrypt_q - decrypt_n)):
                    decrypt_spawn_one()

            if encrypt_q == 0 and len(encrypt_workers) > min_workers:
                extra = len(encrypt_workers) - min_workers
                for t in list(encrypt_workers)[:extra]:
                    t.cancel()
                    await t
            if decrypt_q == 0 and len(decrypt_workers) > min_workers:
                extra = len(decrypt_workers) - min_workers
                for t in list(decrypt_workers)[:extra]:
                    t.cancel()
                    await t

            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            for t in list(encrypt_workers):
                t.cancel()
            for t in list(decrypt_workers):
                t.cancel()

            await asyncio.gather(*list(encrypt_workers), return_exceptions=True)
            await asyncio.gather(*list(decrypt_workers), return_exceptions=True)
            return
        except Exception:
            logger.exception("Dynamic worker scheduling exception")
            await asyncio.sleep(0.5)
