#ifndef RICE_H
#define RICE_H

#define ushort unsigned short
#define MAX_BUF_LEN 4096

#define uchar  unsigned char

int rice_fs(ushort *in, int npts, uchar *out, int start);
void write_zeros(uchar *buf, int len, int x);
void write_bit(uchar *buf, int pos, int value);
int rice_pack(ushort *in, int npts, int bits, uchar *out, int start);
int delta_transform(ushort *in, int npts, ushort *out);
void delta_transform_inverse(ushort *in, int npts, short *out);

int rice_code(ushort *, int, uchar *, int);
int rice_split(ushort *, int, int, uchar *, int);
int rice_uncode(uchar *, int, ushort *, int);
int rice_unfs(uchar *, int, ushort *, int);
int rice_unpack(uchar *, int, int, ushort *, int);
int rice_unsplit(uchar *, int, int, int, short *, int);

int rice_auto(short *in, int npts, int bits, uchar *out, int start);
int rice_unauto(uchar *in, int len, int npts, int bits, short *out);

#endif /* RICE_H */
