#!/usr/bin/python3
import os
import sys
import re
import yaml


#################################
# Util
#################################

def command(cmd):
    print(cmd)
    assert os.system(cmd) == 0    

#################################
# Partition
#################################


def create_using_parted(t):
    def create(config):
        command(f"parted {config['file']} -s -a minimal mktable {t}")
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
        command(f'mkfs.fat -F{size} -s 1 part{parition["num"]}.img')
        if parition['content'] is not None:
            for subdir, dirs, files in os.walk(parition['content']):
                for d in dirs:
                    command(f'mmd -i part{parition["num"]}.img ::{os.path.join(subdir, d)[len(parition["content"]):]}')
                for f in files:
                    command(f'mcopy -i part{parition["num"]}.img {os.path.join(os.path.abspath(subdir), f)} ::{os.path.join(subdir, f)[len(parition["content"]):]}')


    return create

def create_echfs(parition):
    command(f'echfs-utils part{parition["num"]}.img format 512')
    if parition['content'] is not None:
        for subdir, dirs, files in os.walk(parition['content']):
            for d in dirs:
                command(f'echfs-utils part{parition["num"]}.img mkdir {os.path.join(subdir, d)[len(parition["content"]):]}')
            for f in files:
                command(f'echfs-utils part{parition["num"]}.img import {os.path.join(os.path.abspath(subdir), f)} {os.path.join(subdir, f)[len(parition["content"]):]}')


image_fs = {
    'fat12': create_fat(12),
    'fat16': create_fat(16),
    'fat32': create_fat(32),
    'echfs': create_echfs,
}

#################################
# Parsing
#################################

size_shift = {
    'M': 11,
    'G': 21,
}


def main(args):
    # Skip sectors per track check in mtools
    os.environ["MTOOLS_SKIP_CHECK"] = "1"

    if len(args) <= 1:
        print(f"Usage: {args[0]} <config> [alternative file]")
    else:
        with open(args[1], 'rb') as f:
            config = yaml.load(f.read(), Loader=yaml.FullLoader)

        # File override
        if len(args) > 2:
            config['file'] = args[2]

        # Get the image config
        assert 'file' in config, "No filename given :("
        assert 'size' in config, "No size given :("
        ofile = config['file']

        # Get the size
        size_unit = config['size'][-1]
        size_num = int(config['size'][:-1])
        assert size_unit in size_shift, f"Invalid size unit {size_unit}"
        disk_sectors = size_num << size_shift[size_unit]        

        # Create the image itself
        command(f"dd if=/dev/zero of={ofile} bs=1{size_unit} count={config['size'][:-1]}")

        # Parition the image
        assert 'type' in config, "No parition type give :("
        assert config['type'] in image_parition, f"Unsupported partition type {config['type']}, supported: {image_parition.keys()} :("
        image_parition[config['type']](config)

        partition_start = 2048
        partitions = []

        assert 'partitions' in config, "No partitions in config :("
        for partition in config['partitions']:
            assert 'fs' in partition, f"No filesystem given for partition in part {num} :("
            assert partition['fs'] in image_fs, f"Invalid filesystem type {partition['fs']}, supported {image_fs.keys()} :("
            assert 'size' in partition, f"No size given for partition in part {num} :("
            fs = partition['fs']
            label = partition['label']
            num = len(partitions)

            # Calculate size
            if partition['size'] == 'fit':
                sectors = disk_sectors - partition_start - 2048 + 1
            else:
                part_size_unit = partition['size'][-1]
                part_size_num = int(partition['size'][:-1])
                assert part_size_unit in size_shift, f"Invalid size unit {size_unit} in part {num} :("
                sectors = part_size_num << size_shift[size_unit]

            partitions.append({
                'num': num,
                'start': partition_start,
                'end': partition_start + sectors,
                'size': sectors,
                'fs': partition['fs'],
                'bootable': partition['bootable'] if 'bootable' in partition else False,
                'content': partition['content'] if 'content' in partition else None,
                'label': partition['label'] if 'label' in partition else None,
            })
            
            if fs in ['echfs']:
                command(f'parted {ofile} -s -a minimal mkpart {label} {partition_start}s {partition_start + sectors - 1}s')
            else:
                command(f"parted {ofile} -s -a minimal mkpart {label} {fs} {partition_start}s {partition_start + sectors - 1}s")

            if 'bootable' in partition and partition['bootable']:
                command(f"parted {ofile} -s -a minimal toggle {num + 1} boot")
            
            partition_start += sectors

        for partition in partitions:
            command(f"dd if=/dev/zero of=part{partition['num']}.img bs=512 count={partition['size']}")
            image_fs[partition['fs']](partition)
            command(f'dd if=part{partition["num"]}.img of={ofile} bs=512 seek={partition["start"]} count={partition["size"]} conv=notrunc')
            os.unlink(f'part{partition["num"]}.img')

        if config['file'].endswith('.vmdk'):
            command(f'qemu-img convert -f raw -O vmdk {config["file"]} {config["file"]}')
        elif config['file'].endswith('.vdi'):
            command(f'qemu-img convert -f raw -O vdi {config["file"]} {config["file"]}')


if __name__ == "__main__":
    main(sys.argv)
