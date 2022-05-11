#!/usr/bin/python2.7

import binascii
import random
import optparse

# Help Menu
##############################################################################
if __name__=="__main__":

	parser = optparse.OptionParser("usage: %prog -t (e/d) -i (input file) -o (output file)")
	parser.add_option("-t", "--type", dest="Type", type="string", default="NULL",
		help="Encode or Decode (e/d)")
	parser.add_option("-i", "--in", dest="If", default="NULL",
		type="string", help="Set input file (eg: crypt.txt, output.zip,...)")
	parser.add_option("-o", "--out", dest="Of", default="NULL",
		type="string", help="Set output file (eg: crypt.txt, output.zip,...)")

	(options, args) = parser.parse_args()
	if len(args) != 0:
		parser.error("Use -h/--help for help menu...")
        
	Type = options.Type
	Ifile = options.If
	Ofile = options.Of
    
	if Type == "NULL" or Ifile == "NULL" or Ofile == "NULL":
		print "--------------------------------------------------------------------"
		print "|                        GlueGun v1.0 ~ b33f                       |"
		print "|              -HackFu 2012 Stenograpy Encoder/Decoder-            |"
		print "--------------------------------------------------------------------"
		#print ""
		parser.error("Invalid input, check -h/--help for an extended usage menu...")

#############################
# Split Choice Encode/Decode#
#############################

# Encode
##############################################################################
if Type == "e":

# (1) Take RAW binary and convert to hex
# Takes file as input
##############################################################################
	EncodeOrigin = open(Ifile, 'r').read()

	EncodeBinning = binascii.hexlify(EncodeOrigin)

	HexBits = open('/tmp/HexBits.txt', 'w')
	HexBits.write(EncodeBinning)
	HexBits.close()

# (2) Convert hex to Binary-Bits
# Takes /tmp/HexBits.txt as input
##############################################################################
	EncodeHalfWay = open('/tmp/HexBits.txt', 'r').read()

	EncodeHexed_size = len(EncodeHalfWay)*4
	EncodeHexed = (bin(int(EncodeHalfWay, 16))[2:]).zfill(EncodeHexed_size)

	BinBits = open('/tmp/BinBits.txt', 'w')
	BinBits.write(EncodeHexed)
	BinBits.close()

# (1) Convert Binary-Bits to ASCII-Steno
# Takes /tmp/BinBits.txt as input
##############################################################################
	EncodeAllDone = open('/tmp/BinBits.txt', 'r')

	while 1:
		final = open(Ofile, 'a')
		char = EncodeAllDone.read(2)
		if not char: break
		if char == '00':
			Key1 = random.choice('CDGOQSU')
			char = char.replace('00', Key1)
		elif char == '01':
			Key2 = random.choice('ABEFHPR')
			char = char.replace('01', Key2)
		elif char == '10':
			Key3 = random.choice('IJKLTY')
			char = char.replace('10', Key3)
		elif char == '11':
			Key4 = random.choice('MNVWXZ')
			char = char.replace('11', Key4)
		final.write(char)
		final.close()
	EncodeAllDone.close()

# Decode
##############################################################################
elif Type == 'd':

# (1) Convert ASCII-Steno to Binary-Bits...
# Takes text file as input
##############################################################################
	def convert(text, dic):
	    for i, j in dic.iteritems():
	        text = text.replace(i, j)
	    return text

	DecodeOrigin = open(Ifile, 'r').read()

	Keys = {
	'C':'00', 'D':'00', 'G':'00', 'O':'00', 'Q':'00', 'S':'00', 'U':'00',
	'A':'01', 'B':'01', 'E':'01', 'F':'01', 'H':'01', 'P':'01', 'R':'01',
	'I':'10', 'J':'10', 'K':'10', 'L':'10', 'T':'10', 'Y':'10', 'M':'11',
	'N':'11', 'V':'11', 'W':'11', 'X':'11', 'Z':'11'}

	BinBits = open('/tmp/BinBits.txt', 'w')
	BinBits.write(convert(DecodeOrigin, Keys))
	BinBits.close()

# (2) Convert Binary-Bits to hex
# Takes /tmp/BinBits.txt as input
##############################################################################
	DecodeHalfWay = open('/tmp/BinBits.txt', 'r').read()

	DecodeHexed = "%x" % int(DecodeHalfWay, 2)

	HexBits = open('/tmp/HexBits.txt', 'w')
	HexBits.write(DecodeHexed)
	HexBits.close()

# (3) Convert hex to bin
# Takes /tmp/HexBits.txt as input
##############################################################################
	DecodeAllDone = open('/tmp/HexBits.txt', 'r').read()

	DecodeBinning = binascii.unhexlify(DecodeAllDone)

	HexBits = open(Ofile, 'w')
	HexBits.write(DecodeBinning)
	HexBits.close()
