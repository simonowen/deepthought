#!/usr/bin/env python
#
# Extracts individual files from a DTI disk images, as used by the Deep Thought
# floppy disk interface for the Jupiter Ace.
#
# By Simon Owen <simon@simonowen.com>

import os, sys, io, re
import argparse
import struct
from struct import Struct
from operator import xor

# Process command-line options.
parser = argparse.ArgumentParser(description="Extract files from Deep Thought disk images (.dti)")
#parser.add_argument('-t', default=False, action='store_true', help="save files in TAP format")
parser.add_argument('filename', action='store')
args = parser.parse_args()
filename = args.filename

# The catalogue is stored on cyl 0, with a backup copy on cyl 1.
CAT_TRACKS = 2

# Various header structures.
file_header = Struct('<4s2BH')
track_header = Struct('<BH')
cat_header = Struct('<BH')
file_details = Struct('<2H')
tap_header = Struct('<B10s7H')

# Helper class for our simple exceptions.
class DecodeError(Exception):
    pass

# Read and unpack a Deep Thought disk track, throwing exceptions on errors.
def readtrack(cyl):
	f.seek(file_header.size + cyl*tblock, 0)

	flags, datalen = track_header.unpack(f.read(track_header.size))
	if flags and 1:
		raise DecodeError('corrupt track data')
	elif not datalen:
		raise DecodeError('blank track')
	data = f.read(datalen)

	# Strip DOS header from start of real data.
	match = re.search(b'\\xff+\\x2a', data)
	if not match:
		raise DecodeError('missing track header')
	data = data[match.end():]

	# Calculate data checksum by summing data preceding checksum byte.
	calcsum = sum(bytearray(data[:-1])) & 0xff
	checksum = sum(bytearray(data[-1:]))
	if calcsum != checksum:
		raise DecodeError('bad track checksum')

	# Return the data with the checksum byte removed.
	return data[:-1]

try:
  with open(filename, 'rb') as f:
	# Read an unpack the file header, checking the disk image signature.
	sig, cyls, heads, tblock = file_header.unpack(f.read(file_header.size))
	if sig != b'H2G2':
		print("{0} is not a DTI disk image".format(filename))
		exit(1)

	print("{0}: {1} cyls, {2} heads".format(filename, cyls, heads))

	# Read the primary catalogue from cyl 0, but if it fails try the backup
	# copy cyl 1. If both fail there's nothing more we can do.
	try:
		data = readtrack(0)
	except DecodeError as e:
		try:
			data = readtrack(1)
			print('Using backup catalogue')
		except DecodeError as e:
			print('Failed to read either catalogue track!')
			exit(2)

	# Process the directory contents as a file, and read the header.
	t = io.BytesIO(data)
	tracks, block = cat_header.unpack(t.read(cat_header.size))

	# Read the file allocation table, which excludes the catalogue tracks.
	fat = t.read(tracks - CAT_TRACKS)

	files = []
	while 1:
		# Read the filename length and the name itself.
		namelen = struct.unpack('B', t.read(1))[0]
		if not namelen:
			break
		name = t.read(namelen).decode()

		# Read the file size and type.
		size, type = file_details.unpack(t.read(file_details.size))

		# Record an entry for the file, for processing below.
		files.append({ 'name':name, 'size':size, 'type':type, 'data':b'' })

	# Create a sub-directory for the extracted files.
	dir = os.path.splitext(os.path.basename(filename))[0] + '.files'
	os.path.isdir(dir) or os.mkdir(dir)

	print("Extracting {0} files from {1}:".format(len(files), filename))

	# Loop over the entries in the FAT.
	for idx, fileno in enumerate(bytearray(fat)):
		# Take file number from FAT, determine cylinder from index.
		fileno, cyl = fileno, idx + CAT_TRACKS
		if fileno:
			# Simplify indexed access to file entry.
			file = files[fileno - 1]
			try:
				# Read the next track block for this file.
				data = readtrack(cyl)
			except DecodeError as e:
				# Report the problem if the track was not read successfully.
				print("WARNING: {0} on cyl {1} in file '{2}'"
						.format(e, cyl, file['name']))

				# Replace the bad/missing track data with 0xEE filler.
				fillsize = min(block, file['size'] - len(file['data']))
				data = b'\xee' * fillsize
				file['error'] = 1

			# Append the track data to what we've collected so far.
			file['data'] += data

	# Loop over the completed files.
	for file in files:
		# Form output file path, appending a suffix if it's incomplete.
		name = os.path.join(dir, file['name'])
		if 'error' in file:
			name += '-DAMAGED'
		elif file['size'] != len(file['data']):
			name += '-BADSIZE'

		# Use .dict for easy identification of dictionary files.
		if file['type'] == 0:
			name += '.dict'

		# Report the details and write the file content.
		print("Writing {0} ({1} bytes)".format(name, file['size']))
		with open(name, 'wb') as o:
			o.write(file['data'])

		'''
		TODO: determine dict header values, required to export TAP files

		if args.t:
			with open(name + '.tap', 'wb') as o:
				padname = '{0: <10}'.format(file['name'])

				if file['type'] == 0:
					header = tap_header.pack(0x00, padname, file['size'], 0x????, 0x????, 0x????, 0x????, 0x????, 0x????)
				else:
					header = tap_header.pack(0x00, padname, file['size'], 0x2020, 0x2020, 0x2020, 0x2020, 0x2020, 0x2020)

				o.write(struct.pack('<H', len(header) + 1))
				o.write(header)
				o.write(struct.pack('B', reduce(xor, bytearray(header), 0)))

				o.write(struct.pack('<H', len(file['data']) + 1))
				o.write(file['data'])
				o.write(struct.pack('B', reduce(xor, bytearray(file['data']), 0)))
		'''
except IOError as e:
	print(e)
