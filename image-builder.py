#!/usr/bin/python3
import os
import sys
import re
import yaml
import threading


#################################
# Util
#################################

class ThreadPool:

    def __init__(self):
        self._threads = []

    def add_thread(self, proc):
        thrd = threading.Thread(target=proc)
        thrd.start()
        self._threads.append(thrd)

    def join(self):
        for thrd in self._threads:
            thrd.join()
        self._threads.clear()


def c(cmd, expected=[0]):
    print(cmd)
    assert os.system(cmd) in expected


#################################
# Partition
#################################

def create_using_parted(t):
    def create(config):
        c(f"parted {config['file']} -s -a minimal mktable {t}")
    return create


image_parition = {
    'gpt': create_using_parted('gpt'),
    'mbr': create_using_parted('mbr'),
}


#################################
# FS
#################################

def create_fat(size):
    def create(parition):
        c(f'mkfs.fat -F{size} -s 1 part{parition["num"]}.img')
    return create


ECHFS_UTILS = "./echfs/echfs-utils"


def create_ext(typ):
    def create(partition):
        c(f'mke2fs -t ext{typ} part{partition["num"]}.img')
    return create


def create_echfs(parition):
    c(f'{ECHFS_UTILS} part{parition["num"]}.img format 512')


image_fs = {
    'fat12': create_fat(12),
    'fat16': create_fat(16),
    'fat32': create_fat(32),
    'ext2': create_ext(2),
    'ext3': create_ext(3),
    'ext4': create_ext(4),
    'echfs': create_echfs,
}


#################################
# Move files
#################################

def copy_fat(partition):
    partpath = os.path.abspath(f'part{partition["num"]}.img')
    if len(os.listdir(partition["content"])) != 0:
        files = "\" \"".join(os.listdir(partition["content"]))
        c(f'cd {partition["content"]} && mcopy -s -b -i {partpath} -D overwrite "{files}" ::')


def copy_ext(partition):
    for subdir, dirs, files in os.walk(partition['content']):
        for d in dirs:
            c(f'e2mkdir part{partition["num"]}.img:{os.path.join(subdir, d)[len(partition["content"]):]}')
        for f in files:
            c(f'e2cp {os.path.join(os.path.abspath(subdir), f)} part{partition["num"]}.img:{os.path.join(subdir, f)[len(partition["content"]):]}')


def copy_echfs(partition):
    for subdir, dirs, files in os.walk(partition['content']):
        for d in dirs:
            c(f'{ECHFS_UTILS} part{partition["num"]}.img mkdir {os.path.join(subdir, d)[len(partition["content"]):]}')
        for f in files:
            c(f'{ECHFS_UTILS} part{partition["num"]}.img import {os.path.join(os.path.abspath(subdir), f)} {os.path.join(subdir, f)[len(partition["content"]):]}')


copy_files = {
    'fat12': copy_fat,
    'fat16': copy_fat,
    'fat32': copy_fat,
    'ext2': copy_ext,
    'ext3': copy_ext,
    'ext4': copy_ext,
    'echfs': copy_echfs
}

#################################
# Parsing
#################################


size_shift = {
    'M': 11,
    'G': 21,
}


def main(args):
    if len(args) <= 1:
        print(f"Usage: {args[0]} <config> [alternative file]")
    else:
        with open(args[1], 'rb') as f:
            config = yaml.load(f.read(), Loader=yaml.FullLoader)

        # File override
        if len(args) > 2:
            config['file'] = args[2]

        threads = ThreadPool()

        #
        # Get the image config
        #
        assert 'file' in config, "No filename given :("
        assert 'size' in config, "No size given :("
        ofile = config['file']

        #
        # Get the size
        #
        size_unit = config['size'][-1]
        size_num = int(config['size'][:-1])
        assert size_unit in size_shift, f"Invalid size unit {size_unit}"
        disk_sectors = size_num << size_shift[size_unit]

        #
        # Parse the configuration to get a list of partitions
        #
        partitions = []
        partition_start = 2048
        assert 'partitions' in config, "No partitions in config :("
        for partition in config['partitions']:
            assert 'fs' in partition, f"No filesystem given for partition in part {len(partitions)} :("
            assert partition['fs'] in image_fs, f"Invalid filesystem type {partition['fs']}, supported {image_fs.keys()} :("
            assert 'size' in partition, f"No size given for partition in part {len(partitions)} :("

            # Calculate size
            if partition['size'] == 'fit':
                sectors = disk_sectors - partition_start - 2048 + 1
            else:
                part_size_unit = partition['size'][-1]
                part_size_num = int(partition['size'][:-1])
                assert part_size_unit in size_shift, f"Invalid size unit {size_unit} in part {len(partitions)} :("
                sectors = part_size_num << size_shift[size_unit]

            partitions.append({
                'num': len(partitions),
                'start': partition_start,
                'end': partition_start + sectors,
                'size': sectors,
                'fs': partition['fs'],
                'bootable': partition['bootable'] if 'bootable' in partition else False,
                'content': partition['content'] if 'content' in partition else None,
                'label': partition['label'] if 'label' in partition else None,
            })
            partition_start += sectors

        #
        # If the output file does not exists then create a new device with the correct
        # partitions, if it does exist we are going to assume the partitions are correct
        # TODO: maybe don't assume lol
        #
        if not os.path.exists(ofile):

            # Create the image itself
            c(f"dd if=/dev/zero of={ofile} bs=1{size_unit} count={config['size'][:-1]}")

            # Partition the image
            assert 'type' in config, "No parition type give :("
            assert config['type'] in image_parition, f"Unsupported partition type {config['type']}, supported: {image_parition.keys()} :("
            image_parition[config['type']](config)

            num = 1
            for partition in partitions:
                if partition['fs'] in ['echfs']:
                    c(f'parted {ofile} -s -a minimal mkpart {partition["label"]} {partition["start"]}s {partition["end"] - 1}s')
                else:
                    c(f'parted {ofile} -s -a minimal mkpart {partition["label"]} {partition["fs"]} {partition["start"]}s {partition["end"] - 1}s')

                if 'bootable' in partition and partition['bootable']:
                    c(f"parted {ofile} -s -a minimal toggle {num} boot")
                num += 1

            for partition in partitions:
                threads.add_thread(lambda: c(f"dd if=/dev/zero of=part{partition['num']}.img bs=512 count={partition['size']}"))
            threads.join()

            for partition in partitions:
                threads.add_thread(image_fs[partition['fs']](partition))
            threads.join()

        #
        # If the file does not exists then
        #
        else:
            # Convert to a raw image so we can extract the partitions
            if config['file'].endswith('.vmdk'):
                c(f'qemu-img convert -f vmdk -O raw {config["file"]} {config["file"]}')
            elif config['file'].endswith('.vdi'):
                c(f'qemu-img convert -f vdi -O raw {config["file"]} {config["file"]}')

            # extract all of the partitions
            for partition in partitions:
                threads.add_thread(lambda: c(f'dd if={ofile} of=part{partition["num"]}.img bs=512 skip={partition["start"]} count={partition["size"]}'))
            threads.join()

        # copy all of the files (will not delete ones)
        for partition in partitions:
            if partition['content'] is not None:
                threads.add_thread(lambda: copy_files[partition['fs']](partition))
        threads.join()

        # Cleanup all of the left over partitions
        for partition in partitions:
            c(f'dd if=part{partition["num"]}.img of={ofile} bs=512 seek={partition["start"]} count={partition["size"]} conv=notrunc')
            os.unlink(f'part{partition["num"]}.img')

        # convert to the wanted image
        if config['file'].endswith('.vmdk'):
            c(f'qemu-img convert -f raw -O vmdk {config["file"]} {config["file"]}')
        elif config['file'].endswith('.vdi'):
            c(f'qemu-img convert -f raw -O vdi {config["file"]} {config["file"]}')


if __name__ == "__main__":
    main(sys.argv)
