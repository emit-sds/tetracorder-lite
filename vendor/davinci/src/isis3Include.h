#ifndef ISIS3INCLUDE_H_
#define ISIS3INCLUDE_H_


typedef struct minISISINFO {

	/* Core */
	int StartByte;
	char *Format;
	int TileSamples;
	int TileLines;

	/* Dimensions */
	int Samples;
	int Lines;
	int Bands;

	/* Pixels */
	char *Type;
	char *ByteOrder;
	double Base;
	double Multiplier;

	/* Label */
	int Bytes;

} minIsisInfo;




#endif /* ISIS3INCLUDE_H_ */
